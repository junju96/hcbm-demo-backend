# -*- coding: utf-8 -*-
"""plan uuid 测试 — 编辑保存写入时间戳后六位；发布/控制指令的 tid 优先取 uuid"""
import unittest
from unittest.mock import patch

from app.services import action_sequence_client as asc


class TestTidFromPlanUuid(unittest.TestCase):
    def test_int_uuid(self):
        self.assertEqual(asc._tid_from_plan_uuid({"uuid": 123456}), 123456)

    def test_str_uuid(self):
        self.assertEqual(asc._tid_from_plan_uuid({"uuid": "654321"}), 654321)

    def test_missing_uuid(self):
        self.assertIsNone(asc._tid_from_plan_uuid({}))
        self.assertIsNone(asc._tid_from_plan_uuid(None))
        self.assertIsNone(asc._tid_from_plan_uuid({"uuid": ""}))

    def test_invalid_uuid(self):
        self.assertIsNone(asc._tid_from_plan_uuid({"uuid": "abc"}))


class TestBuildMissionDataTid(unittest.TestCase):
    def _plan(self, **kw):
        plan = {"plan_id": "plan-0002", "title": "t", "stages": [], "vehicle_summary": []}
        plan.update(kw)
        return plan

    def test_uuid_becomes_tid(self):
        data = asc.build_mission_data(self._plan(uuid=456789))
        self.assertEqual(data["task"]["tid"], 456789)

    def test_no_uuid_falls_back_to_plan_id(self):
        data = asc.build_mission_data(self._plan())
        self.assertEqual(data["task"]["tid"], 2)

    def test_explicit_tid_wins_over_uuid(self):
        data = asc.build_mission_data(self._plan(uuid=456789), tid=777)
        self.assertEqual(data["task"]["tid"], 777)


class TestControlMissionTid(unittest.TestCase):
    def test_control_uses_uuid_when_present(self):
        with patch.object(asc, "get_plan_detail_operator", return_value={"uuid": 111222}), \
             patch.object(asc, "get_plan_detail", return_value=None):
            _, payload = asc.build_control_mission_payload("plan-0002", 1, vehicle_vid="ZD01")
        self.assertEqual(payload["args"]["taskid"], 111222)

    def test_control_falls_back_without_uuid(self):
        with patch.object(asc, "get_plan_detail_operator", return_value=None), \
             patch.object(asc, "get_plan_detail", return_value={"plan_id": "plan-0002"}):
            _, payload = asc.build_control_mission_payload("plan-0002", 1, vehicle_vid="ZD01")
        self.assertEqual(payload["args"]["taskid"], 2)


class TestFetchPlanDocumentUuid(unittest.TestCase):
    def test_uuid_recovered_from_raw_payload(self):
        doc = {
            "resource_id": "plan:plan-0002", "task_type": "PLAN", "plan_id": "plan-0002",
            "raw_payload": {"plan_id": "plan-0002", "uuid": 246810},
            "attributes": {}, "source": {},
        }
        result = asc._fetch_plan_document("plan:plan-0002", lambda path, **kw: doc)
        self.assertEqual(result["uuid"], 246810)
        self.assertNotIn("raw_payload", result)

    def test_projection_uuid_wins(self):
        doc = {
            "resource_id": "plan:plan-0002", "task_type": "PLAN", "plan_id": "plan-0002",
            "uuid": 111, "raw_payload": {"uuid": 222},
        }
        result = asc._fetch_plan_document("plan:plan-0002", lambda path, **kw: doc)
        self.assertEqual(result["uuid"], 111)


class TestFrontendPlanUuidPassthrough(unittest.TestCase):
    def test_uuid_passed_through(self):
        plan = {"plan_id": "plan-0002", "uuid": 345678, "stages": [], "teams": []}
        result = asc._to_frontend_plan(plan, [])
        self.assertEqual(result["uuid"], 345678)

    def test_uuid_default_none(self):
        result = asc._to_frontend_plan({"plan_id": "plan-0002"}, [])
        self.assertIsNone(result["uuid"])


if __name__ == "__main__":
    unittest.main()
