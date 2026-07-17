import unittest
from unittest.mock import MagicMock, patch

from app.services import task_monitoring_client as tm


class TestSendWarningsIfAny(unittest.TestCase):
    def setUp(self):
        tm.clear_warning_signatures("p1", "DC01")

    @patch("app.services.task_monitoring_client.requests.post")
    @patch("app.services.task_monitoring_client.detection_result_to_text", return_value="偏离提醒")
    def test_deviation_warning_sent_once_and_deduped(self, _mock_text, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()

        result = {
            "ok": True,
            "data": {
                "vehicle_id": "DC01",
                "is_deviated": True,
                "matched_segment_index": 2,
                "distance_to_route_m": 12.4,
            },
        }
        tm.send_warnings_if_any("p1", "DC01", "/monitor/check-deviation", result)
        self.assertEqual(mock_post.call_count, 1)

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["monitor_report"]["warning_type"], "route_deviation")
        self.assertEqual(payload["monitor_report"]["equipment_ids"], ["DC01"])
        self.assertEqual(payload["monitor_report"]["action_ids"], [])

        # 同一异常再次上报应被去重
        tm.send_warnings_if_any("p1", "DC01", "/monitor/check-deviation", result)
        self.assertEqual(mock_post.call_count, 1)

    @patch("app.services.task_monitoring_client.requests.post")
    @patch("app.services.task_monitoring_client.detection_result_to_text", return_value="超时提醒")
    def test_timeout_warning_action_ids(self, _mock_text, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()

        result = {
            "ok": True,
            "data": {
                "vehicles": {
                    "DC01": {
                        "timeout_warnings": [
                            {
                                "action_seq": 3,
                                "expected_end_time": 60,
                                "timeout_duration": 5,
                                "status": "in_progress",
                            }
                        ],
                        "progress": {"completed": 1, "total": 2, "progress": 50.0},
                    }
                }
            },
        }
        tm.send_warnings_if_any("p1", "DC01", "/timeout/actions/status", result)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["monitor_report"]["warning_type"], "task_deviation")
        self.assertEqual(payload["monitor_report"]["action_ids"], ["3"])

    @patch("app.services.task_monitoring_client.requests.post")
    @patch("app.services.task_monitoring_client.detection_result_to_text", return_value="偏离提醒")
    def test_failed_send_not_deduped(self, _mock_text, mock_post):
        mock_post.side_effect = Exception("boom")
        result = {
            "ok": True,
            "data": {"vehicle_id": "DC01", "is_deviated": True, "matched_segment_index": 2},
        }
        tm.send_warnings_if_any("p1", "DC01", "/monitor/check-deviation", result)
        self.assertEqual(mock_post.call_count, 1)

        # 失败后应允许重试
        mock_post.side_effect = None
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()
        tm.send_warnings_if_any("p1", "DC01", "/monitor/check-deviation", result)
        self.assertEqual(mock_post.call_count, 2)


class TestPollWiring(unittest.TestCase):
    @patch("app.services.task_monitoring_client.send_warnings_if_any")
    @patch("app.services.task_monitoring_client.check_deviation")
    @patch("app.services.task_monitoring_client.lookahead_warning")
    @patch("app.services.task_monitoring_client.report_position")
    @patch("app.services.task_monitoring_client.report_action_status")
    def test_poll_once_triggers_warnings(
        self, mock_status, _mock_pos, mock_look, mock_dev, mock_send
    ):
        mock_status.return_value = {
            "ok": True,
            "data": {
                "vehicles": {
                    "DC01": {
                        "timeout_warnings": [],
                        "progress": {"completed": 0, "total": 1},
                    }
                }
            },
        }
        mock_look.return_value = {"ok": True, "data": {"warnings": []}}
        mock_dev.return_value = {
            "ok": True,
            "data": {"vehicle_id": "DC01", "is_deviated": False},
        }
        tm._poll_once("p1", "DC01", {"title": "test-plan"})
        self.assertEqual(mock_send.call_count, 3)
