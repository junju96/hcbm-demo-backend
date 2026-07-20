import unittest
from datetime import datetime, timedelta, timezone

from app.services.action_sequence_client import (
    _normalize_action_timing,
    _parse_duration_to_seconds,
    _parse_start_time,
)


class TestActionTimingNormalization(unittest.TestCase):
    def _make_plan(self, actions_per_vehicle=None, created_at=None):
        actions_per_vehicle = actions_per_vehicle or {}
        if created_at is None:
            created_at = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        stages = []
        for stage_seq, vehicles in actions_per_vehicle.items():
            stage_vehicles = []
            for vid, actions in vehicles.items():
                stage_vehicles.append({"vid": vid, "actions": actions})
            stages.append({
                "stage_id": f"stage-{stage_seq}",
                "stage_seq": stage_seq,
                "team_actions": {"team-1": stage_vehicles},
            })
        return {
            "plan_id": "plan-test",
            "created_at": created_at,
            "stages": stages,
        }

    def test_missing_params_filled_with_defaults(self):
        plan = self._make_plan({
            1: {
                "DC01": [
                    {"action_seq": 1, "param": {}},
                    {"action_seq": 2, "param": {}},
                ]
            }
        })
        _normalize_action_timing(plan)

        params1 = plan["stages"][0]["team_actions"]["team-1"][0]["actions"][0]["param"]
        params2 = plan["stages"][0]["team_actions"]["team-1"][0]["actions"][1]["param"]

        self.assertEqual(params1["mission_duration"], "00:00:10")
        self.assertTrue(params1["enable_start_time"])
        start1 = _parse_start_time(params1["start_time"])
        self.assertIsNotNone(start1)

        self.assertEqual(params2["mission_duration"], "00:00:10")
        start2 = _parse_start_time(params2["start_time"])
        self.assertEqual(start2, start1 + timedelta(seconds=10))

    def test_zero_values_replaced(self):
        plan = self._make_plan({
            1: {
                "DC01": [
                    {"action_seq": 1, "param": {"start_time": "", "mission_duration": "00:00:00"}},
                ]
            }
        })
        _normalize_action_timing(plan)
        params = plan["stages"][0]["team_actions"]["team-1"][0]["actions"][0]["param"]
        self.assertEqual(params["mission_duration"], "00:00:10")
        self.assertNotEqual(params["start_time"], "")
        self.assertTrue(params["enable_start_time"])

    def test_valid_values_preserved(self):
        base = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
        plan = self._make_plan({
            1: {
                "DC01": [
                    {
                        "action_seq": 1,
                        "param": {
                            "start_time": base.isoformat(),
                            "mission_duration": "00:00:30",
                        },
                    },
                ]
            }
        })
        _normalize_action_timing(plan)
        params = plan["stages"][0]["team_actions"]["team-1"][0]["actions"][0]["param"]
        self.assertEqual(params["start_time"], base.isoformat())
        self.assertEqual(params["mission_duration"], "00:00:30")

    def test_cross_stage_predecessor(self):
        base = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
        plan = self._make_plan({
            1: {
                "DC01": [
                    {"action_seq": 1, "param": {"start_time": base.isoformat(), "mission_duration": "00:00:15"}},
                ]
            },
            2: {
                "DC01": [
                    {"action_seq": 1, "param": {}},
                ]
            },
        })
        _normalize_action_timing(plan)
        stage2_params = plan["stages"][1]["team_actions"]["team-1"][0]["actions"][0]["param"]
        expected_start = base + timedelta(seconds=15)
        self.assertEqual(_parse_start_time(stage2_params["start_time"]), expected_start)
        self.assertEqual(stage2_params["mission_duration"], "00:00:10")

    def test_per_vehicle_isolation(self):
        plan = self._make_plan({
            1: {
                "DC01": [{"action_seq": 1, "param": {}}],
                "XL01": [{"action_seq": 1, "param": {}}],
            }
        })
        _normalize_action_timing(plan)
        vehicles = plan["stages"][0]["team_actions"]["team-1"]
        dc_params = [v for v in vehicles if v["vid"] == "DC01"][0]["actions"][0]["param"]
        xl_params = [v for v in vehicles if v["vid"] == "XL01"][0]["actions"][0]["param"]
        self.assertEqual(dc_params["mission_duration"], "00:00:10")
        self.assertEqual(xl_params["mission_duration"], "00:00:10")
        # 不同车辆的首个 action 都应使用 plan 创建时间
        self.assertEqual(_parse_start_time(dc_params["start_time"]), _parse_start_time(xl_params["start_time"]))


class TestDurationParsing(unittest.TestCase):
    def test_hhmmss(self):
        self.assertEqual(_parse_duration_to_seconds("00:01:05"), 65)

    def test_mmss(self):
        self.assertEqual(_parse_duration_to_seconds("01:05"), 65)

    def test_seconds(self):
        self.assertEqual(_parse_duration_to_seconds("65"), 65)

    def test_zero(self):
        self.assertEqual(_parse_duration_to_seconds("00:00:00"), 0)
        self.assertEqual(_parse_duration_to_seconds(""), 0)


class TestStartTimeParsing(unittest.TestCase):
    def test_iso(self):
        dt = datetime(2026, 7, 17, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(_parse_start_time(dt.isoformat()), dt)

    def test_invalid(self):
        self.assertIsNone(_parse_start_time(""))
        self.assertIsNone(_parse_start_time("not-a-time"))
