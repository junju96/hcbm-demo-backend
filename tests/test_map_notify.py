import re
import unittest
from unittest.mock import patch

from app.services.action_sequence_client import (
    notify_plan_map_clicked,
    notify_plan_map_clicked_coordinator,
    notify_plan_map_clicked_operator,
)


class TestNotifyPlanMapClicked(unittest.TestCase):
    def test_patch_path_and_body(self):
        captured = {}

        def _fake(path, json_body=None, silent=False):
            captured["path"] = path
            captured["body"] = json_body
            return {"ok": True}

        result = notify_plan_map_clicked("plan-1020", _fake, "data_server")
        self.assertTrue(result["ok"])
        self.assertEqual(captured["path"], "/api/v1/task_pool/resources/plan:plan-1020")
        self.assertEqual(list(captured["body"].keys()), ["payload"])
        self.assertRegex(captured["body"]["payload"]["last_click"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(result["plan_id"], "plan-1020")
        self.assertIn("last_click", result)

    def test_rid_prefix_not_duplicated(self):
        captured = {}

        def _fake(path, json_body=None, silent=False):
            captured["path"] = path
            return {"ok": True}

        notify_plan_map_clicked("plan:plan-1020", _fake)
        self.assertEqual(captured["path"], "/api/v1/task_pool/resources/plan:plan-1020")

    def test_patch_failure_returns_not_ok(self):
        def _fail(path, json_body=None, silent=False):
            return None

        result = notify_plan_map_clicked("plan-1020", _fail)
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_seat_wrappers_route_to_correct_http(self):
        with patch("app.services.action_sequence_client._http_patch") as m_coord, \
             patch("app.services.action_sequence_client._http_patch_operator") as m_op:
            m_coord.return_value = {"ok": True}
            m_op.return_value = {"ok": True}
            notify_plan_map_clicked_coordinator("plan-1")
            notify_plan_map_clicked_operator("plan-2")
            m_coord.assert_called_once()
            m_op.assert_called_once()
            self.assertIn("plan:plan-1", m_coord.call_args[0][0])
            self.assertIn("plan:plan-2", m_op.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
