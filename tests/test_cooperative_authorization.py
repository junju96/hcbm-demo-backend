# -*- coding: utf-8 -*-
"""set_cooperative_authorization 测试 — 下发授权/解除授权 payload 构建"""
import unittest
from unittest.mock import patch

from app.services import action_sequence_client as asc


class TestBuildCooperativeAuthorizationPayload(unittest.TestCase):
    def test_grant_carries_all_args(self):
        vehicles = [
            {"vmf": 100220000, "vip": "25.11.1.3"},
            {"vmf": 100220001, "vip": "25.11.1.4"},
        ]
        p = asc.build_cooperative_authorization_payload(
            source=1, command=1, vehicles=vehicles, target_type=17, priorities=[1, 2],
        )
        self.assertEqual(p["service"], "MissionService")
        self.assertEqual(p["action"], "set_cooperative_authorization")
        self.assertEqual(p["args"], {
            "source": 1, "command": 1,
            "vehicles": vehicles,
            "target_type": 17, "priorities": [1, 2],
        })

    def test_release_carries_full_args(self):
        # 解除授权也必须带齐 vehicles/target_type/priorities，缺字段会被 MissionService 丢弃
        vehicles = [{"vmf": 100220000, "vip": "25.11.1.3"}]
        p = asc.build_cooperative_authorization_payload(
            source=1, command=2, vehicles=vehicles, target_type=17, priorities=[1],
        )
        self.assertEqual(p["args"], {
            "source": 1, "command": 2,
            "vehicles": vehicles,
            "target_type": 17, "priorities": [1],
        })

    def test_release_defaults_full_shape(self):
        p = asc.build_cooperative_authorization_payload(command=2)
        self.assertEqual(p["args"], {
            "source": 1, "command": 2, "vehicles": [], "target_type": 0, "priorities": [],
        })

    def test_grant_defaults(self):
        p = asc.build_cooperative_authorization_payload(command=1)
        self.assertEqual(p["args"]["vehicles"], [])
        self.assertEqual(p["args"]["target_type"], 0)
        self.assertEqual(p["args"]["priorities"], [])


class TestPublishCooperativeAuthorization(unittest.TestCase):
    def test_topic_and_publish(self):
        with patch.object(asc.zenoh_client, "publish", return_value=True) as mock_pub:
            ok, msg = asc.publish_cooperative_authorization("equipment:ZD01", command=1, vehicles=[{"vmf": 1, "vip": "25.11.1.3"}], target_type=2, priorities=[3])
        self.assertTrue(ok)
        topic, payload = mock_pub.call_args[0]
        self.assertEqual(topic, "op/t01/g01/vZD01/cmd/MissionService/set_cooperative_authorization")
        self.assertEqual(payload["action"], "set_cooperative_authorization")

    def test_publish_failure(self):
        with patch.object(asc.zenoh_client, "publish", return_value=False), \
             patch.object(asc.zenoh_client, "get_last_zenoh_error", return_value="boom"):
            ok, msg = asc.publish_cooperative_authorization("ZD01", command=2)
        self.assertFalse(ok)
        self.assertIn("boom", msg)


if __name__ == "__main__":
    unittest.main()
