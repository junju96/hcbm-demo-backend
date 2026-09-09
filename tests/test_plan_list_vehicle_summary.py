# -*- coding: utf-8 -*-
"""plan 列表接口轻量 vehicle_summary 测试 — 前端按车型过滤不再 N+1 拉详情"""
import unittest

from app.services import action_sequence_client as asc


def _plan_with_teams():
    return {
        "plan_id": "plan-t1",
        "resource_id": "plan:plan-t1",
        "title": "测试方案",
        "teams": [
            {"team_id": "TEAM_NEW", "vehicles": [{"vid": "equipment:ZD01", "resource_type": "Recon-Strike-UGV"}]},
        ],
        "stages": [
            {
                "stage_id": "s1",
                "team_actions": [
                    {
                        "team_id": "TEAM_NEW",
                        "car_actions": [
                            {
                                "vid": "equipment:ZD01",
                                "actions": [
                                    {"action_id": "a1", "action_type": "auto-move", "name": "自主机动", "param": {"points": []}},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }


class TestVehicleSummaryBrief(unittest.TestCase):
    def test_brief_carries_vid_and_resource_type(self):
        brief = asc._build_vehicle_summary_brief(_plan_with_teams())
        self.assertEqual(len(brief), 1)
        self.assertEqual(brief[0]["vid"], "equipment:ZD01")
        self.assertEqual(brief[0]["resource_type"], "Recon-Strike-UGV")
        # 轻量摘要不含 stages 等重字段
        self.assertNotIn("stages", brief[0])

    def test_empty_plan_returns_empty(self):
        self.assertEqual(asc._build_vehicle_summary_brief({"plan_id": "p", "stages": []}), [])


if __name__ == "__main__":
    unittest.main()


class TestLeaderFirstOrdering(unittest.TestCase):
    """编队机动方案：DS 投影会重排 car_actions，头车靠 param.is_leader 排到第一行"""

    def _plan(self):
        return {
            "plan_id": "plan-f1",
            "title": "编队方案",
            "teams": [{"team_id": "T1", "vehicles": [
                {"vid": "equipment:ZD01", "resource_type": "Recon-Strike-UGV"},
                {"vid": "equipment:DC01", "resource_type": "Electronic-UGV"},
            ]}],
            "stages": [{
                "stage_id": "s1",
                "team_actions": [{"team_id": "T1", "car_actions": [
                    # DS 投影后的顺序（按 id 字母序），头车 ZD01 在尾部
                    {"vid": "equipment:DC01", "actions": [
                        {"action_id": "a1", "action_type": "formation-move", "name": "编队机动", "param": {"points": []}},
                    ]},
                    {"vid": "equipment:ZD01", "actions": [
                        {"action_id": "a2", "action_type": "formation-move", "name": "编队机动", "param": {"points": [], "is_leader": True}},
                    ]},
                ]}],
            }],
        }

    def test_leader_vehicle_comes_first(self):
        plan = self._plan()
        ca = asc._build_car_actions_from_plan(plan)
        full = asc._to_frontend_plan(plan, ca)
        vids = [v["vid"] for v in full["vehicle_summary"]]
        self.assertEqual(vids[0], "equipment:ZD01")

    def test_no_marker_keeps_original_order(self):
        plan = self._plan()
        # 去掉 is_leader 标记
        plan["stages"][0]["team_actions"][0]["car_actions"][1]["actions"][0]["param"].pop("is_leader")
        ca = asc._build_car_actions_from_plan(plan)
        full = asc._to_frontend_plan(plan, ca)
        vids = [v["vid"] for v in full["vehicle_summary"]]
        self.assertEqual(vids, ["equipment:DC01", "equipment:ZD01"])
