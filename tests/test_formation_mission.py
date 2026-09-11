# -*- coding: utf-8 -*-
"""编队机动任务下发测试 — 编队行动抽取、头车排序、body 构建与 HTTP POST 下发"""
import unittest
from unittest.mock import patch, MagicMock

from app.services import action_sequence_client as asc


def _move_action(name="自主机动"):
    return {
        "action_type": "auto-move",
        "name": name,
        "action_seq": 1,
        "param": {"points": [{"lon": 116.1, "lat": 39.7, "alt": 0}], "limited_speed": 20},
    }


def _formation_action(is_leader=False):
    return {
        "action_type": "formation-move",
        "name": "编队机动",
        "action_seq": 1,
        "param": {
            "points": [{"lon": 116.129136, "lat": 39.767262, "alt": 0, "offsetX": 0, "offsetY": 0}],
            "limited_speed": 20,
            "formation_mode": 0,
            "safe_mode": 0,
            **({"is_leader": True} if is_leader else {}),
        },
    }


def _plan(car_actions):
    """构造最小 plan：单个 stage / 单个 team，car_actions 按传入顺序（模拟 DS 重排后顺序）。"""
    return {
        "plan_id": "plan-000099",
        "title": "编队测试",
        "stages": [
            {
                "stage_id": "STAGE_1",
                "team_actions": [
                    {
                        "team_id": "TEAM_1",
                        "car_actions": [
                            {"vid": vid, "actions": actions} for vid, actions in car_actions
                        ],
                    }
                ],
            }
        ],
        # vehicle_summary 不应影响编队抽取（会被剔除）
        "vehicle_summary": [{"vid": "DC01", "stages": [{"actions": [_move_action()]}]}],
    }


# VMF 映射：避免测试依赖车辆控制缓存/资源池（网络）
_VMFS = {"ZD01": 100220000, "DC01": 100220001, "KD01": 100220002}


def _mock_vehicle_lookups():
    return (
        patch.object(asc.vehicle_control_client, "get_vehicle_vmf", side_effect=lambda vid: _VMFS.get(vid)),
        patch.object(asc.vehicle_control_client, "get_vehicle_ip", return_value=None),
        patch.object(asc, "get_online_vehicle_info_from_resource_pool", return_value=None),
    )


class TestIsFormationMoveAction(unittest.TestCase):
    def test_by_action_type(self):
        self.assertTrue(asc._is_formation_move_action({"action_type": "formation-move", "param": {}}))

    def test_by_name(self):
        self.assertTrue(asc._is_formation_move_action({"action_type": "Unknown_Action", "name": "编队机动", "param": {}}))

    def test_by_param(self):
        action = {"action_type": "Unknown_Action", "param": {"points": [], "formation_mode": 0}}
        self.assertTrue(asc._is_formation_move_action(action))

    def test_auto_move_not_matched(self):
        self.assertFalse(asc._is_formation_move_action(_move_action()))


class TestExtractFormationSubPlan(unittest.TestCase):
    def test_filters_non_formation_and_leader_first(self):
        # DS 投影重排后头车 ZD01 不在首位，需按 is_leader 恢复
        plan = _plan([
            ("DC01", [_formation_action()]),
            ("ZD01", [_move_action(), _formation_action(is_leader=True)]),
            ("KD01", [_move_action()]),  # 无编队行动，应被剔除
        ])
        sub, leader = asc._extract_formation_sub_plan(plan)
        self.assertEqual(leader, "ZD01")
        self.assertNotIn("vehicle_summary", sub)
        kept = sub["stages"][0]["team_actions"][0]["car_actions"]
        self.assertEqual([ca["vid"] for ca in kept], ["ZD01", "DC01"])
        # 头车只保留编队机动行动
        self.assertEqual(len(kept[0]["actions"]), 1)
        self.assertEqual(kept[0]["actions"][0]["action_type"], "formation-move")


class TestBuildFormationMissionBody(unittest.TestCase):
    def test_body_structure_and_leader_first(self):
        plan = _plan([
            ("DC01", [_formation_action()]),
            ("ZD01", [_formation_action(is_leader=True)]),
        ])
        m1, m2, m3 = _mock_vehicle_lookups()
        with m1, m2, m3:
            body, vids, leader = asc.build_formation_mission_body(plan)
        task = body["task"]
        self.assertEqual([v["vid"] for v in task["vehicles"]], [_VMFS["ZD01"], _VMFS["DC01"]])
        self.assertEqual(vids, ["ZD01", "DC01"])
        self.assertEqual(leader, "ZD01")
        # 编队机动行动 service sid=7
        svc = task["vehicles"][0]["acts"][0]["service"]
        self.assertEqual(svc["sid"], 7)


class TestPublishFormationMissionIfAny(unittest.TestCase):
    def test_no_formation_action(self):
        plan = _plan([("ZD01", [_move_action()])])
        with patch.object(asc, "get_plan_detail", return_value=plan):
            result = asc.publish_formation_mission_if_any("plan-000099")
        self.assertFalse(result["sent"])

    def test_plan_not_found(self):
        with patch.object(asc, "get_plan_detail", return_value=None):
            result = asc.publish_formation_mission_if_any("plan-x")
        self.assertFalse(result["sent"])

    def test_post_to_formation_service_leader_first(self):
        plan = _plan([
            ("DC01", [_formation_action()]),
            ("ZD01", [_formation_action(is_leader=True)]),
        ])
        resp = MagicMock(ok=True, status_code=200)
        resp.json.return_value = {"code": 0}
        m1, m2, m3 = _mock_vehicle_lookups()
        with patch.object(asc, "get_plan_detail", return_value=plan), m1, m2, m3, \
             patch.object(asc.requests, "post", return_value=resp) as mock_post:
            result = asc.publish_formation_mission_if_any("plan-000099")
        self.assertTrue(result["sent"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)
        self.assertEqual(result["leader_vid"], "ZD01")
        self.assertEqual(result["vehicle_count"], 2)
        # 只 POST 一次到编队任务下发接口，body 直接是 {"task": ...}
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.args[0], asc.FORMATION_MISSION_SEND_URL)
        body = mock_post.call_args.kwargs["json"]
        vehicles = body["task"]["vehicles"]
        self.assertEqual(vehicles[0]["vid"], _VMFS["ZD01"])
        self.assertEqual(vehicles[1]["vid"], _VMFS["DC01"])

    def test_post_failure(self):
        plan = _plan([("ZD01", [_formation_action(is_leader=True)])])
        m1, m2, m3 = _mock_vehicle_lookups()
        with patch.object(asc, "get_plan_detail", return_value=plan), m1, m2, m3, \
             patch.object(asc.requests, "post", side_effect=Exception("boom")):
            result = asc.publish_formation_mission_if_any("plan-000099")
        self.assertTrue(result["sent"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "boom")


if __name__ == "__main__":
    unittest.main()
