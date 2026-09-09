# -*- coding: utf-8 -*-
"""task_received_status 监听测试 — zenoh 反馈 → SSE 推送前端"""
import json
import unittest
from unittest.mock import patch

from app.services import action_sequence_client as asc
from app.services import zenoh_client


class TestFeedbackListenerRegistry(unittest.TestCase):
    def tearDown(self):
        # 清理测试注册的监听器，避免污染全局
        zenoh_client._feedback_listeners.clear()

    def test_listener_called_on_feedback(self):
        seen = []
        zenoh_client.register_feedback_listener(seen.append)
        msg = {"topic": "op/t01/g01/vZD04/mission/mission_status", "payload_text": "{}"}
        zenoh_client._on_feedback_message(msg)
        self.assertEqual(seen, [msg])

    def test_listener_error_does_not_break_cache(self):
        def boom(_msg):
            raise RuntimeError("boom")

        zenoh_client.register_feedback_listener(boom)
        zenoh_client._on_feedback_message({"topic": "t", "payload_text": "{}"})
        # 消息仍被缓存
        self.assertIn("t", zenoh_client._feedback_buffers)

    def test_duplicate_registration_ignored(self):
        def cb(_msg):
            pass

        zenoh_client.register_feedback_listener(cb)
        zenoh_client.register_feedback_listener(cb)
        self.assertEqual(zenoh_client._feedback_listeners.count(cb), 1)


class TestOnTaskReceivedStatus(unittest.TestCase):
    def _msg(self, payload, topic="op/t01/g01/vZD04/mission/task_received_status"):
        return {"topic": topic, "payload_text": json.dumps(payload, ensure_ascii=False)}

    def test_pushes_sse_event(self):
        payload = {"tid": 718710, "recv_num": 1, "received_aids": [{"aid": 3, "status": 0}],
                   "vehicle_id": "ZD04", "VMF": 100220000}
        with patch.object(asc, "_push_plan_sse_event") as mock_push:
            asc._on_task_received_status(self._msg(payload))
        mock_push.assert_called_once()
        event, data = mock_push.call_args[0]
        self.assertEqual(event, "action_sequence.task_received")
        self.assertEqual(data["tid"], 718710)
        self.assertEqual(data["vehicle_id"], "ZD04")
        self.assertEqual(data["vmf"], 100220000)
        self.assertEqual(data["received_aids"], [{"aid": 3, "status": 0}])

    def test_ignores_other_topics(self):
        with patch.object(asc, "_push_plan_sse_event") as mock_push:
            asc._on_task_received_status(
                self._msg({"tid": 1}, topic="op/t01/g01/vZD04/mission/mission_status")
            )
        mock_push.assert_not_called()

    def test_ignores_missing_tid(self):
        with patch.object(asc, "_push_plan_sse_event") as mock_push:
            asc._on_task_received_status(self._msg({"vehicle_id": "ZD04"}))
        mock_push.assert_not_called()

    def test_accepts_dict_payload(self):
        msg = {"topic": "op/t01/g01/vZD04/mission/task_received_status",
               "payload": {"tid": 42, "vehicle_id": "ZD04"}}
        with patch.object(asc, "_push_plan_sse_event") as mock_push:
            asc._on_task_received_status(msg)
        self.assertEqual(mock_push.call_args[0][1]["tid"], 42)


if __name__ == "__main__":
    unittest.main()
