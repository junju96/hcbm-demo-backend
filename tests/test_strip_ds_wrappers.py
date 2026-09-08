# -*- coding: utf-8 -*-
"""_strip_ds_wrappers / _import_plan_payload 对 dependencies 字段的处理测试

背景：DS 会给每个资源附加 dependencies 字段（plan/team/stage 上通常为 []），
而 ACTION 上的 dependencies 就是业务字段（行动依赖，如 ["1"]），且 DS 的类型化
投影会把它与包装键（attributes/relations 等）放在同一字典里，无法靠结构区分。
dependencies 是扁平列表，原样写回不会嵌套加深，因此一律保留、不剥离。
（2026-09-07 踩坑：旧实现递归剥离 dependencies，sync/编辑保存后行动依赖被清空，
前端 DAG 布局退化为单列纵向堆叠。）
"""
import unittest

from app.services import action_sequence_client as asc


def _plan_with_ds_dependencies():
    """模拟从 DS 读回的 plan 文档：嵌套 action 的 dependencies 与包装键同级共存"""
    return {
        "resource_id": "plan:plan-t1",
        "task_type": "PLAN",
        "plan_id": "plan-t1",
        "attributes": {},
        "relations": [],
        "dependencies": [],
        "stages": [
            {
                "stage_id": "s1",
                "attributes": {},
                "relations": [],
                "dependencies": [],
                "team_actions": [
                    {
                        "team_id": "t1",
                        "car_actions": [
                            {
                                "vid": "equipment:ZD01",
                                "actions": [
                                    # DS 类型化投影形态：业务 dependencies 与包装键同级
                                    {"action_id": "a1", "action_seq": 1, "param": {},
                                     "attributes": {}, "relations": [], "dependencies": []},
                                    {"action_id": "a2", "action_seq": 2, "param": {},
                                     "attributes": {}, "relations": [], "dependencies": ["1"]},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


class TestStripDsWrappersDependencies(unittest.TestCase):
    def test_all_dependencies_preserved(self):
        out = asc._strip_ds_wrappers(_plan_with_ds_dependencies())
        self.assertEqual(out["dependencies"], [])
        self.assertEqual(out["stages"][0]["dependencies"], [])
        actions = out["stages"][0]["team_actions"][0]["car_actions"][0]["actions"]
        self.assertEqual(actions[0]["dependencies"], [])
        self.assertEqual(actions[1]["dependencies"], ["1"])

    def test_wrapper_keys_still_stripped(self):
        out = asc._strip_ds_wrappers(_plan_with_ds_dependencies())
        self.assertNotIn("attributes", out)
        self.assertNotIn("relations", out)
        self.assertNotIn("attributes", out["stages"][0])
        actions = out["stages"][0]["team_actions"][0]["car_actions"][0]["actions"]
        self.assertNotIn("attributes", actions[0])
        self.assertNotIn("relations", actions[0])

    def test_internal_keys_still_stripped(self):
        plan = _plan_with_ds_dependencies()
        plan["_seat"] = "operator"
        plan["local_dirty"] = True
        out = asc._strip_ds_wrappers(plan)
        self.assertNotIn("_seat", out)
        self.assertNotIn("local_dirty", out)


class TestImportPlanPayloadDependencies(unittest.TestCase):
    def test_import_payload_keeps_dependencies(self):
        captured = {}

        def fake_post(path, body, **kwargs):
            captured["body"] = body
            return {"ok": True}

        ok = asc._import_plan_payload("plan:plan-t1", _plan_with_ds_dependencies(), fake_post)
        self.assertTrue(ok)
        payload = captured["body"]["resources"][0]
        actions = payload["stages"][0]["team_actions"][0]["car_actions"][0]["actions"]
        # 业务 dependencies 必须随写回保留，否则 DS 会把行动依赖清空
        self.assertEqual(actions[1].get("dependencies"), ["1"])
        # 包装键仍然剥离
        self.assertNotIn("attributes", payload)


if __name__ == "__main__":
    unittest.main()
