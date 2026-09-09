# -*- coding: utf-8 -*-
"""编队机动（sid=7）测试 — action_type 解析与下发 payload 构建"""
import unittest

from app.services import action_sequence_client as asc


def _formation_action():
    return {
        "action_type": "Unknown_Action",
        "name": "编队机动",
        "param": {
            "points": [
                {"lon": 116.129136, "lat": 39.767262, "alt": 0, "offsetX": 5, "offsetY": -10},
                {"lon": 116.130386, "lat": 39.767011, "alt": 0, "offsetX": 0, "offsetY": 0},
            ],
            "limited_speed": 20,
            "formation_mode": 1,
            "safe_mode": 0,
        },
    }


class TestFormationMoveResolve(unittest.TestCase):
    def test_infer_from_param(self):
        param = _formation_action()["param"]
        self.assertEqual(asc._infer_action_type_from_param(param), "formation-move")

    def test_infer_from_name(self):
        self.assertEqual(asc._infer_action_type_from_name("编队机动"), "formation-move")

    def test_sid_is_7(self):
        self.assertEqual(asc._resolve_sid("Recon-Strike-UGV", "formation-move", "编队机动"), 7)

    def test_auto_move_not_confused(self):
        # points + limited_speed 但无 formation_mode 时仍是自主机动
        param = {"points": [{"lon": 1, "lat": 2, "alt": 0}], "limited_speed": 20}
        self.assertEqual(asc._infer_action_type_from_param(param), "auto-move")


class TestFormationMovePayload(unittest.TestCase):
    def test_payload_carries_offsets(self):
        svc = asc._build_service_from_action(_formation_action(), "Recon-Strike-UGV")
        self.assertEqual(svc["sid"], 7)
        self.assertEqual(svc["formation_mode"], 1)
        self.assertEqual(svc["limited_speed"], 20)
        pt = svc["points"][0]
        self.assertEqual(pt["offsetX"], 5)
        self.assertEqual(pt["offsetY"], -10)
        # 编队机动路径点不带 radius/type
        self.assertNotIn("radius", pt)
        self.assertNotIn("type", pt)

    def test_payload_defaults(self):
        svc = asc._build_service_from_action({"action_type": "formation-move", "param": {}}, "")
        self.assertEqual(svc["sid"], 7)
        self.assertEqual(svc["points"], [])
        self.assertEqual(svc["formation_mode"], 0)


if __name__ == "__main__":
    unittest.main()
