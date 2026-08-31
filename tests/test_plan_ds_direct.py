import copy
import unittest

from app.services.action_sequence_client import (
    sync_plan_to_data_server,
    update_action_param,
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
        self.assertEqual(plan["title"], "测试方案")  # plan_title 归一化为 title
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


if __name__ == "__main__":
    unittest.main()
