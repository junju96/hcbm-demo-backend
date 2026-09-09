# -*- coding: utf-8 -*-
"""set_cooperative_authorization 测试 — 下发授权/解除授权 payload 构建"""
import unittest
from unittest.mock import patch

from app.services import action_sequence_client as asc


class TestBuildCooperativeAuthorizationPayload(unittest.TestCase):
    def test_grant_carries_all_args(self):
        p = asc.build_cooperative_authorization_payload(
            source=1, command=1, vehicles=[100220000, 100220001], target_type=17, priorities=[1, 2],
        )
        self.assertEqual(p["service"], "MissionService")
        self.assertEqual(p["action"], "set_cooperative_authorization")
        self.assertEqual(p["args"], {
            "source": 1, "command": 1,
            "vehicles": [100220000, 100220001],
            "target_type": 17, "priorities": [1, 2],
        })

    def test_release_only_source_and_command(self):
        p = asc.build_cooperative_authorization_payload(
            source=1, command=2, vehicles=[100220000], target_type=17, priorities=[1],
        )
        self.assertEqual(p["args"], {"source": 1, "command": 2})

    def test_grant_defaults(self):
        p = asc.build_cooperative_authorization_payload(command=1)
        self.assertEqual(p["args"]["vehicles"], [])
        self.assertEqual(p["args"]["target_type"], 0)
        self.assertEqual(p["args"]["priorities"], [])


class TestPublishCooperativeAuthorization(unittest.TestCase):
    def test_topic_and_publish(self):
        with patch.object(asc.zenoh_client, "publish", return_value=True) as mock_pub:
            ok, msg = asc.publish_cooperative_authorization("equipment:ZD01", command=1, vehicles=[1], target_type=2, priorities=[3])
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
