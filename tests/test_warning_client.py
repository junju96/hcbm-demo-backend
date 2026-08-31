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


class TestConflictPrecheckWarningPayload(unittest.TestCase):
    def setUp(self):
        tm.clear_warning_signatures("p1", "ZD01")

    _INTERVAL = {
        "vehicle_a": "equipment:ZD01",
        "vehicle_b": "equipment:ZD03",
        "t_start": 40.0,
        "t_end": 50.0,
        "peak_distance_m": 0.8,
        "peak_t": 45.0,
        "conflict_info": {
            "vehicle_a": "equipment:ZD01",
            "plan_a": "plan-0001",
            "vehicle_b": "equipment:ZD03",
            "plan_b": "plan-0002",
            "conflict_point": {"lon": 116.119, "lat": 39.75},
        },
    }

    @patch("app.services.task_monitoring_client.requests.post")
    def test_precheck_warning_carries_conflict_info(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()

        result = {"ok": True, "data": {"conflict_intervals": [self._INTERVAL]}}
        tm.send_warnings_if_any("p1", "ZD01", "/conflict/validate", result)

        payload = mock_post.call_args.kwargs["json"]
        report = payload["monitor_report"]
        # conflict_info 原样透传（保留 equipment: 前缀）
        self.assertEqual(report["conflict_info"], self._INTERVAL["conflict_info"])
        # 文本中去前缀
        self.assertIn("车辆 ZD01（方案 plan-0001）", report["warning_content"])
        self.assertNotIn("equipment:", report["warning_content"])

    @patch("app.services.task_monitoring_client.requests.post")
    def test_precheck_warning_without_conflict_info_omits_field(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()

        interval = {k: v for k, v in self._INTERVAL.items() if k != "conflict_info"}
        result = {"ok": True, "data": {"conflict_intervals": [interval]}}
        tm.send_warnings_if_any("p1", "ZD01", "/conflict/validate", result)

        report = mock_post.call_args.kwargs["json"]["monitor_report"]
        self.assertNotIn("conflict_info", report)

    @patch("app.services.task_monitoring_client.requests.post")
    def test_realtime_warning_has_no_conflict_info(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()

        result = {
            "ok": True,
            "data": {
                "warnings": [
                    {
                        "vehicle_id": "ZD01",
                        "matched_segment_index": 1,
                        "conflict_intervals": [self._INTERVAL],
                    }
                ]
            },
        }
        tm.send_warnings_if_any("p1", "ZD01", "/monitor/lookahead-warning", result)

        report = mock_post.call_args.kwargs["json"]["monitor_report"]
        self.assertNotIn("conflict_info", report)


class TestRealtimeConflictDedup(unittest.TestCase):
    """临机冲突预警：同一任务内 同一车辆对+同一类型 只上报一次；且两次上报有最小间隔阈值。"""

    def setUp(self):
        tm.clear_warning_signatures("p1", "ZD01")

    def _result(self, segment, t_start, t_end, vehicle_b="equipment:XL02"):
        return {
            "ok": True,
            "data": {
                "warnings": [
                    {
                        "vehicle_id": "ZD01",
                        "matched_segment_index": segment,
                        "conflict_intervals": [
                            {
                                "vehicle_a": "equipment:ZD01",
                                "vehicle_b": vehicle_b,
                                "t_start": t_start,
                                "t_end": t_end,
                                "peak_distance_m": 0.5,
                                "peak_t": t_start,
                            }
                        ],
                    }
                ]
            },
        }

    @patch("app.services.task_monitoring_client.requests.post")
    def test_same_pair_same_type_reported_once(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()

        # 同一车辆对、同一类型：时间漂移、换路线段都不再重复上报
        tm.send_warnings_if_any("p1", "ZD01", "/monitor/lookahead-warning", self._result(6, 40.0, 50.0))
        tm.send_warnings_if_any("p1", "ZD01", "/monitor/lookahead-warning", self._result(6, 45.0, 55.0))
        tm.send_warnings_if_any("p1", "ZD01", "/monitor/lookahead-warning", self._result(7, 50.5, 60.5))
        self.assertEqual(mock_post.call_count, 1)

    @patch("app.services.task_monitoring_client.requests.post")
    def test_min_interval_throttles_distinct_reports(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()

        with patch("app.services.task_monitoring_client.time.time") as mock_time:
            mock_time.return_value = 1000.0
            # 不同车辆对（新签名），但距上次同类型上报不足 60s → 被节流
            tm.send_warnings_if_any("p1", "ZD01", "/monitor/lookahead-warning", self._result(6, 40.0, 50.0))
            mock_time.return_value = 1005.0
            tm.send_warnings_if_any(
                "p1", "ZD01", "/monitor/lookahead-warning", self._result(6, 40.0, 50.0, vehicle_b="equipment:ZD03")
            )
            self.assertEqual(mock_post.call_count, 1)

            # 超过 60s 后允许再次上报
            mock_time.return_value = 1061.0
            tm.send_warnings_if_any(
                "p1", "ZD01", "/monitor/lookahead-warning", self._result(6, 40.0, 50.0, vehicle_b="equipment:ZD03")
            )
            self.assertEqual(mock_post.call_count, 2)

    @patch("app.services.task_monitoring_client.requests.post")
    def test_precheck_same_pair_reported_once(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"received": True}
        mock_post.return_value.raise_for_status = MagicMock()

        def precheck(t_start, t_end):
            return {
                "ok": True,
                "data": {
                    "conflict_intervals": [
                        {
                            "vehicle_a": "equipment:ZD01",
                            "vehicle_b": "equipment:XL02",
                            "t_start": t_start,
                            "t_end": t_end,
                            "peak_distance_m": 0.8,
                            "peak_t": t_start,
                        }
                    ]
                },
            }

        tm.send_warnings_if_any("p1", "ZD01", "/conflict/validate", precheck(40.0, 50.0))
        tm.send_warnings_if_any("p1", "ZD01", "/conflict/validate", precheck(45.0, 55.0))
        self.assertEqual(mock_post.call_count, 1)


class TestPollSourceCompletion(unittest.TestCase):
    """轮询接口逻辑：每类检测首次上报成功后停掉该类接口轮询；全部完成后结束轮询。"""

    def setUp(self):
        tm.clear_warning_signatures("p1", "ZD01")

    def tearDown(self):
        tm.stop_monitoring("p1", "ZD01")

    @patch("app.services.task_monitoring_client.send_warnings_if_any")
    @patch("app.services.task_monitoring_client.check_deviation")
    @patch("app.services.task_monitoring_client.lookahead_warning")
    @patch("app.services.task_monitoring_client.report_position")
    @patch("app.services.task_monitoring_client.report_action_status")
    def test_source_stops_after_first_report(
        self, mock_status, mock_pos, mock_look, mock_dev, mock_send
    ):
        # 超时状态无预警、不完成；临机预警首次即上报成功；偏离无异常
        mock_status.return_value = {"ok": True, "data": {"vehicles": {"ZD01": {"progress": {"completed": 0, "total": 1}}}}}
        mock_look.return_value = {"ok": True, "data": {"warnings": []}}
        mock_dev.return_value = {"ok": True, "data": {"is_deviated": False}}

        def send_side_effect(plan_id, vid, source, result, plan_name=None):
            return source == "/monitor/lookahead-warning"

        mock_send.side_effect = send_side_effect

        tm._poll_once("p1", "ZD01", {"title": "t"})
        tm._poll_once("p1", "ZD01", {"title": "t"})

        # 临机预警首次上报成功后不再轮询；其余接口继续
        self.assertEqual(mock_look.call_count, 1)
        self.assertEqual(mock_status.call_count, 2)
        self.assertEqual(mock_dev.call_count, 2)
        self.assertEqual(mock_pos.call_count, 2)

    @patch("app.services.task_monitoring_client.send_warnings_if_any", return_value=True)
    @patch("app.services.task_monitoring_client.check_deviation")
    @patch("app.services.task_monitoring_client.lookahead_warning")
    @patch("app.services.task_monitoring_client.report_position")
    @patch("app.services.task_monitoring_client.report_action_status")
    def test_all_sources_done_stops_polling(
        self, mock_status, mock_pos, mock_look, mock_dev, mock_send
    ):
        mock_status.return_value = {"ok": True, "data": {"vehicles": {"ZD01": {"progress": {"completed": 0, "total": 1}}}}}
        mock_look.return_value = {"ok": True, "data": {"warnings": []}}
        mock_dev.return_value = {"ok": True, "data": {"is_deviated": False}}

        # 需要计时器占位，stop_monitoring 才有状态可清
        tm._active_timers[tm._monitor_key("p1", "ZD01")] = None
        tm._poll_once("p1", "ZD01", {"title": "t"})
        # 三类检测全部上报成功 → 整个轮询结束（定时器移除，之后不会再有轮询周期触发）
        self.assertNotIn(tm._monitor_key("p1", "ZD01"), tm._active_timers)
        self.assertEqual(mock_status.call_count, 1)
        self.assertEqual(mock_look.call_count, 1)
        self.assertEqual(mock_dev.call_count, 1)


class TestReportTimeBase(unittest.TestCase):
    """超时状态上报的时间基准：与注册的预计完成时间对齐。"""

    def setUp(self):
        tm.clear_warning_signatures("p1", "ZD01")
        tm._monitor_start_times.clear()

    def _plan(self, start_time):
        return {
            "plan_id": "p1",
            "vehicle_summary": [
                {
                    "vid": "ZD01",
                    "stages": [
                        {
                            "stage_seq": 1,
                            "actions": [
                                {"action_id": "a1", "action_seq": 1, "state": "in_progress",
                                 "param": {"start_time": start_time, "mission_duration": "00:05:05"}}
                            ],
                        }
                    ],
                }
            ],
        }

    @patch("app.services.task_monitoring_client.requests.post")
    def test_relative_start_time_reports_elapsed_seconds(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {}
        mock_post.return_value.raise_for_status = MagicMock()

        # 1970 基准的相对时间 → update_time 应为距任务开始的秒数（~100），而非 Unix 纪元
        tm._monitor_start_times[tm._monitor_key("p1", "ZD01")] = 1000.0
        with patch("app.services.task_monitoring_client.time.time", return_value=1100.0):
            tm.report_action_status("ZD01", self._plan("1970-01-01 08:03:33"))

        payload = mock_post.call_args.kwargs["json"]
        update_time = payload["vehicles"]["ZD01"][0]["update_time"]
        self.assertAlmostEqual(update_time, 100.0, places=1)

    @patch("app.services.task_monitoring_client.requests.post")
    def test_absolute_start_time_reports_epoch(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {}
        mock_post.return_value.raise_for_status = MagicMock()

        with patch("app.services.task_monitoring_client.time.time", return_value=1786411833.0):
            tm.report_action_status("ZD01", self._plan("2026-08-11 09:00:00"))

        payload = mock_post.call_args.kwargs["json"]
        update_time = payload["vehicles"]["ZD01"][0]["update_time"]
        self.assertAlmostEqual(update_time, 1786411833.0, places=1)


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
