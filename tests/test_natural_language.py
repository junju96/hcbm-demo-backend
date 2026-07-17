import unittest

from app.services.natural_language import DetectionType, detection_result_to_text


class TestNaturalLanguage(unittest.TestCase):
    def test_route_deviation(self):
        text = detection_result_to_text(
            DetectionType.ROUTE_DEVIATION,
            {
                "vehicle_id": "DC01",
                "timestamp": 25,
                "distance_to_route_m": 12.4,
                "is_deviated": True,
                "matched_segment_index": 2,
            },
        )
        self.assertIn("DC01", text)
        self.assertIn("12.4 米", text)
        self.assertIn("路线段 2", text)

    def test_task_timeout(self):
        text = detection_result_to_text(
            "/timeout/actions/status",
            {
                "vehicles": {
                    "DC01": {
                        "timeout_warnings": [
                            {
                                "action_seq": 1,
                                "expected_end_time": 60,
                                "timeout_duration": 5,
                                "status": "in_progress",
                            }
                        ],
                        "progress": {"completed": 1, "total": 2, "progress": 50.0},
                    }
                }
            },
            plan_name="区域巡控方案",
        )
        self.assertIn("区域巡控方案", text)
        self.assertIn("行动 1", text)
        self.assertIn("50%", text)

    def test_conflict_precheck(self):
        text = detection_result_to_text(
            DetectionType.ROUTE_CONFLICT_PRECHECK,
            {
                "conflict_intervals": [
                    {
                        "vehicle_a": "DC01",
                        "vehicle_b": "XL01",
                        "t_start": 40.0,
                        "t_end": 50.0,
                        "peak_distance_m": 0.8,
                        "peak_t": 45.0,
                    }
                ]
            },
        )
        self.assertIn("DC01", text)
        self.assertIn("XL01", text)
        self.assertIn("0.8 米", text)
