import copy
import unittest

from app.services.action_sequence_client import (
    sync_plan_to_data_server,
    update_action_param,
    update_plan,
)
from app.services.task_pool import task_pool


def _make_doc():
    """模拟 GET /resources/{rid} 返回的 plan 全文档（含包装层键）。"""
    return {
        "resource_id": "plan:plan-t1",
        "task_type": "PLAN",
        "plan_id": "plan-t1",
        "plan_title": "测试方案",
        "state": "DRAFT",
        "attributes": {"cache_key": "plan:plan-t1"},
        "raw_payload": {"should": "be-stripped"},
        "teams": [],
        "targets": [],
        "stages": [
            {
                "stage_id": "st1",
                "stage_seq": 1,
                "team_actions": [
                    {
                        "team_id": "team1",
                        "car_actions": [
                            {
                                "car_actions_id": "ca1",
                                "vid": "ZD01",
                                "actions": [
                                    {
                                        "action_id": "act_001",
                                        "action_seq": 1,
                                        "action_type": "Lens-Recon",
                                        "param": {"rounds": 1},
                                        "state": "INIT",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


class FakeHttp:
    """记录调用的假 http_get/http_post。"""

    def __init__(self, doc=None):
        self.doc = doc
        self.imports = []

    def get(self, path, params=None, silent=False):
        if self.doc is not None and "/resources/plan:plan-t1" in path and "/simple/" not in path:
            return copy.deepcopy(self.doc)
        return None

    def post(self, path, body, silent=False, timeout=None):
        if "ingestion/import" in path:
            self.imports.append(body)
            return {"status": "ok"}
        return None


def _imported_plan(fake):
    return fake.imports[-1]["resources"][0]


def _make_ds_style_doc():
    """模拟 DS 全文档：DS 原始字段命名 + 嵌套子资源带完整包装层。"""
    return {
        "resource_id": "plan:plan-t1",
        "task_type": "PLAN",
        "plan_id": "plan-t1",
        "plan_title": "测试方案",
        "plan_description": "描述",
        "state": "SCHEDULED",
        "command_id": "command-1008",
        "mission_ids": ["mission-0001"],
        "tactic": {"tactic_id": "tactic-1", "main_tactic": "地面无人车协同侦察"},
        "last_click": "2026-09-03 11:00:00",
        "replaces_plan_id": None,
        "attributes": {"cache_key": "plan:plan-t1"},
        "search_text": "PLAN 测试方案",
        "source": {"source_type": "api"},
        "raw_payload": {"should": "be-stripped"},
        "relations": [{"type": "has", "target": "team:team1"}],
        "created_at": "2026-09-01T00:00:00",
        "updated_at": "2026-09-01T00:00:00",
        "teams": [
            {
                "resource_id": "team:team1",
                "task_type": "TEAM",
                "team_id": "team1",
                "team_name": "地面侦察组",
                "team_equipments": ["equipment:ZD01"],
                "state": "SCHEDULED",
                "attributes": {"cache_key": "plan:plan-t1"},
                "search_text": "TEAM 地面侦察组",
                "source": {"source_type": "api"},
                "raw_payload": {"nested": "wrapper"},
                "relations": [],
                "created_at": "2026-09-01T00:00:00",
                "updated_at": "2026-09-01T00:00:00",
            }
        ],
        "targets": [{"target_id": "t1", "target_name": "目标1"}],
        "stages": [
            {
                "resource_id": "stage:st1",
                "task_type": "STAGE",
                "stage_id": "st1",
                "stage_seq": 1,
                "stage_title": "集结准备",
                "stage_description": "阶段描述",
                "attributes": {},
                "search_text": "STAGE 集结准备",
                "raw_payload": {"nested": True},
                "team_actions": [
                    {
                        "team_id": "team1",
                        "car_actions": [
                            {
                                "resource_id": "car_actions:ca1",
                                "task_type": "CAR_ACTIONS",
                                "car_actions_id": "ca1",
                                "vid": "equipment:ZD01",
                                "attributes": {},
                                "raw_payload": {"nested": True},
                                "actions": [
                                    {
                                        "resource_id": "action:act_001",
                                        "task_type": "ACTION",
                                        "action_id": "act_001",
                                        "action_seq": 1,
                                        "action_type": "Lens-Recon",
                                        "action_name": "侦察",
                                        "param": {"rounds": 1},
                                        "state": "SCHEDULED",
                                        "attributes": {},
                                        "search_text": "ACTION 侦察",
                                        "raw_payload": {"nested": True},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


_WRAPPER_KEYS = {
    "attributes", "raw_payload", "search_text", "source",
    "relations", "connections", "dependencies", "created_at", "updated_at",
}


class TestSyncDsDirect(unittest.TestCase):
    def setUp(self):
        task_pool.clear()

    def test_sync_prefers_ds_document_over_local_cache(self):
        """本地有缓存（非 dirty）时，sync 仍以数据服务器全文档为准。"""
        task_pool.set("plan:plan-t1", {"plan_id": "plan-t1", "title": "本地旧版", "stages": [], "_seat": "data_server"})
        fake = FakeHttp(doc=_make_doc())

        ok = sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        self.assertTrue(ok)
        plan = _imported_plan(fake)
        self.assertEqual(plan["plan_title"], "测试方案")  # 写回保持 DS 原始命名
        self.assertEqual(len(plan["stages"]), 1)  # stages 来自 DS 而非本地空 stages
        self.assertNotIn("raw_payload", plan)
        self.assertNotIn("_seat", plan)

    def test_sync_pushes_dirty_local_first(self):
        """本地有未推送修改（local_dirty 且同席位）时优先推送本地。"""
        task_pool.set(
            "plan:plan-t1",
            {"plan_id": "plan-t1", "title": "本地未推送", "stages": [], "_seat": "data_server", "local_dirty": True},
        )
        fake = FakeHttp(doc=_make_doc())

        ok = sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        self.assertTrue(ok)
        self.assertEqual(_imported_plan(fake)["title"], "本地未推送")
        # 推送成功后缓存清 dirty
        self.assertFalse(task_pool.get("plan:plan-t1").get("local_dirty"))

    def test_sync_ds_down_falls_back_to_same_seat_cache(self):
        fake = FakeHttp(doc=None)
        task_pool.set("plan:plan-t1", {"plan_id": "plan-t1", "title": "本地兜底", "stages": [], "_seat": "data_server"})

        ok = sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        self.assertTrue(ok)
        self.assertEqual(_imported_plan(fake)["title"], "本地兜底")

    def test_sync_ds_down_ignores_other_seat_cache(self):
        """数据服务器不可达且本地缓存属于另一席位时，不得使用该缓存。"""
        fake = FakeHttp(doc=None)
        task_pool.set("plan:plan-t1", {"plan_id": "plan-t1", "title": "他席位数据", "stages": [], "_seat": "operator"})

        ok = sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        self.assertFalse(ok)
        self.assertEqual(fake.imports, [])


class TestUpdateActionParamDsDirect(unittest.TestCase):
    def setUp(self):
        task_pool.clear()

    def test_update_param_reads_ds_and_writes_back(self):
        """参数编辑直读 DS 全文档，修改后 import 写回。"""
        fake = FakeHttp(doc=_make_doc())

        # update_action_param 内部用模块级 _http_get/_http_post，这里通过 monkeypatch 替换
        import app.services.action_sequence_client as asc

        orig_get, orig_post = asc._http_get, asc._http_post
        asc._http_get, asc._http_post = fake.get, fake.post
        try:
            ok = update_action_param("plan-t1", "act_001", {"rounds": 10})
        finally:
            asc._http_get, asc._http_post = orig_get, orig_post

        self.assertTrue(ok)
        plan = _imported_plan(fake)
        action = plan["stages"][0]["team_actions"][0]["car_actions"][0]["actions"][0]
        self.assertEqual(action["param"], {"rounds": 10})

    def test_update_param_ignores_other_seat_cache_when_ds_down(self):
        import app.services.action_sequence_client as asc

        fake = FakeHttp(doc=None)
        task_pool.set(
            "plan:plan-t1",
            {**_make_doc(), "_seat": "operator", "title": "他席位"},
        )
        orig_get, orig_post = asc._http_get, asc._http_post
        asc._http_get, asc._http_post = fake.get, fake.post
        try:
            ok = update_action_param("plan-t1", "act_001", {"rounds": 10})
        finally:
            asc._http_get, asc._http_post = orig_get, orig_post

        self.assertFalse(ok)
        self.assertEqual(fake.imports, [])


class TestWritebackFidelity(unittest.TestCase):
    """写回数据服务器时以 DS 原文为准：不丢字段、不改命名、剥离嵌套包装层与内部键。"""

    def setUp(self):
        task_pool.clear()

    def test_writeback_preserves_full_document_fields(self):
        """不再做白名单挑选：tactic/command_id/mission_ids/last_click 等字段必须保留。"""
        fake = FakeHttp(doc=_make_ds_style_doc())

        ok = sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        self.assertTrue(ok)
        plan = _imported_plan(fake)
        for key in (
            "plan_title", "plan_description", "command_id", "mission_ids",
            "tactic", "last_click", "replaces_plan_id", "teams", "targets", "stages",
        ):
            self.assertIn(key, plan, f"字段 {key} 被白名单丢弃")
        self.assertEqual(plan["plan_title"], "测试方案")

    def test_writeback_strips_nested_wrappers(self):
        """嵌套子资源的 DS 包装层键必须剥离，防止往返嵌套加深。"""
        fake = FakeHttp(doc=_make_ds_style_doc())

        sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        plan = _imported_plan(fake)
        self.assertTrue(_WRAPPER_KEYS.isdisjoint(plan.keys()), f"plan 顶层仍含包装键: {_WRAPPER_KEYS & plan.keys()}")
        team = plan["teams"][0]
        self.assertTrue(_WRAPPER_KEYS.isdisjoint(team.keys()), f"team 仍含包装键: {_WRAPPER_KEYS & team.keys()}")
        stage = plan["stages"][0]
        self.assertTrue(_WRAPPER_KEYS.isdisjoint(stage.keys()), f"stage 仍含包装键: {_WRAPPER_KEYS & stage.keys()}")
        car_actions = stage["team_actions"][0]["car_actions"][0]
        self.assertTrue(_WRAPPER_KEYS.isdisjoint(car_actions.keys()), f"car_actions 仍含包装键: {_WRAPPER_KEYS & car_actions.keys()}")
        action = car_actions["actions"][0]
        self.assertTrue(_WRAPPER_KEYS.isdisjoint(action.keys()), f"action 仍含包装键: {_WRAPPER_KEYS & action.keys()}")

    def test_writeback_keeps_ds_field_names(self):
        """写回保持 DS 原始命名，不做 plan_title->title 等归一化。"""
        fake = FakeHttp(doc=_make_ds_style_doc())

        sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        plan = _imported_plan(fake)
        self.assertIn("plan_title", plan)
        self.assertNotIn("title", plan)
        team = plan["teams"][0]
        self.assertIn("team_name", team)
        self.assertIn("team_equipments", team)
        self.assertNotIn("name", team)
        self.assertNotIn("vehicles", team)
        stage = plan["stages"][0]
        self.assertIn("stage_title", stage)
        self.assertNotIn("title", stage)
        action = stage["team_actions"][0]["car_actions"][0]["actions"][0]
        self.assertIn("action_name", action)
        self.assertNotIn("name", action)

    def test_writeback_strips_internal_and_derived_keys(self):
        """本地内部键（_seat/local_dirty）与顶层派生键（car_actions/vehicle_summary）不得写入 DS。"""
        doc = {**_make_ds_style_doc(), "_seat": "data_server", "local_dirty": True,
               "car_actions": [{"vid": "ZD01"}], "vehicle_summary": [{"vid": "ZD01"}]}
        task_pool.set("plan:plan-t1", doc)  # dirty 缓存优先推送
        fake = FakeHttp(doc=_make_ds_style_doc())

        ok = sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        self.assertTrue(ok)
        plan = _imported_plan(fake)
        self.assertNotIn("_seat", plan)
        self.assertNotIn("local_dirty", plan)
        self.assertNotIn("car_actions", plan)  # 顶层派生键剥离
        self.assertNotIn("vehicle_summary", plan)
        # stages 内 team_actions 的 car_actions 是 DS 原生结构，必须保留
        self.assertIn("car_actions", plan["stages"][0]["team_actions"][0])

    def test_writeback_ensures_identity_keys(self):
        """保底 resource_id/task_type/plan_id 三个标识键。"""
        fake = FakeHttp(doc=_make_ds_style_doc())

        sync_plan_to_data_server("plan-t1", fake.post, fake.get, label="data_server")

        plan = _imported_plan(fake)
        self.assertEqual(plan["resource_id"], "plan:plan-t1")
        self.assertEqual(plan["task_type"], "PLAN")
        self.assertEqual(plan["plan_id"], "plan-t1")


class TestUpdatePlanDsNaming(unittest.TestCase):
    """update_plan：前端命名的编辑字段映射到 DS 命名写回；返回前端的副本仍是归一化命名。"""

    def setUp(self):
        task_pool.clear()

    def test_payload_frontend_keys_mapped_to_ds_names(self):
        import app.services.action_sequence_client as asc

        fake = FakeHttp(doc=_make_ds_style_doc())
        orig_get, orig_post = asc._http_get, asc._http_post
        asc._http_get, asc._http_post = fake.get, fake.post
        try:
            result = update_plan("plan-t1", {"title": "新标题", "state": "ACTIVE"})
        finally:
            asc._http_get, asc._http_post = orig_get, orig_post

        plan = _imported_plan(fake)
        self.assertEqual(plan["plan_title"], "新标题")
        self.assertNotIn("title", plan)
        self.assertEqual(plan["state"], "ACTIVE")
        # 返回给前端的副本保持归一化命名
        self.assertEqual(result["title"], "新标题")
        self.assertEqual(result["state"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
