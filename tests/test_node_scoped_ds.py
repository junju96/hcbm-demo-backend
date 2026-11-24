# -*- coding: utf-8 -*-
"""协同席 / 操控席 task 域按 node_id 隔离读写。"""
import copy
import unittest
from unittest.mock import patch

from app.services import action_sequence_client as asc
from app.services import data_server_client as dsc
from app.services.task_pool import task_pool


def _plan(resource_id="plan:plan-0060", node_id="1"):
    return {
        "resource_id": resource_id,
        "task_type": "PLAN",
        "plan_id": "plan-0060",
        "plan_title": "节点方案",
        "node_id": node_id,
        "teams": [],
        "targets": [],
        "stages": [],
    }


class TestNodeResourceIds(unittest.TestCase):
    def test_operator_suffix_is_added_idempotently(self):
        self.assertEqual(dsc._resource_id_for_node("plan:plan-0060", "2"), "plan:plan-0060@2")
        self.assertEqual(dsc._resource_id_for_node("plan:plan-0060@2", "2"), "plan:plan-0060@2")
        self.assertEqual(dsc._resource_id_for_node("plan:plan-0060", "1"), "plan:plan-0060")

    def test_business_plan_id_never_contains_node_suffix(self):
        self.assertEqual(dsc._resource_id_without_node("plan:plan-0060@2"), "plan:plan-0060")
        self.assertEqual(dsc._resource_id_without_node("plan-0060@2"), "plan-0060")

    def test_operator_resource_path_uses_node_copy(self):
        path = dsc._operator_resource_path("/api/v1/task_pool/resources/simple/plan:plan-0060")
        self.assertEqual(path, "/api/v1/task_pool/resources/simple/plan:plan-0060@2")
        path = dsc._operator_resource_path("/api/v1/task_pool/resources/car_actions:ca-1/delete")
        self.assertEqual(path, "/api/v1/task_pool/resources/car_actions:ca-1@2/delete")
        self.assertEqual(
            dsc._operator_resource_path("/api/v1/task_pool/resources/query"),
            "/api/v1/task_pool/resources/query",
        )


class TestNodeListQuery(unittest.TestCase):
    def test_gateway_list_filters_kind_node_and_legacy_main(self):
        captured = {}

        def fake_get(path, params=None, silent=False, timeout=None):
            captured["path"] = path
            captured["params"] = params
            return {"items": [
                _plan(),
                _plan(node_id=None),
                _plan("plan:plan-0060@2", "2"),
                {"resource_id": "action:action-1@2", "task_type": "ACTION", "node_id": "2"},
            ], "total": 4}

        main = dsc._query_resources_for_node(fake_get, "PLAN", "1", 200)
        operator = dsc._query_resources_for_node(fake_get, "PLAN", "2", 200)

        self.assertEqual([p["resource_id"] for p in main], ["plan:plan-0060", "plan:plan-0060"])
        self.assertEqual([p["resource_id"] for p in operator], ["plan:plan-0060@2"])
        self.assertEqual(captured["path"], "/api/v1/task_pool/resources")
        self.assertEqual(captured["params"]["node_id"], "2")

    def test_plan_lists_use_their_own_node(self):
        raw = {"items": [_plan(), _plan("plan:plan-0060@2", "2")]}
        with patch.object(asc, "_http_get", return_value=raw) as coord_get, \
             patch.object(asc, "_http_get_operator", return_value=raw) as operator_get:
            asc.query_plans()
            asc.query_plans_operator()
        self.assertEqual(coord_get.call_args.kwargs["params"]["node_id"], "1")
        self.assertEqual(operator_get.call_args.kwargs["params"]["node_id"], "2")


class TestOperatorReadWrite(unittest.TestCase):
    def setUp(self):
        task_pool.clear()

    def tearDown(self):
        task_pool.clear()

    def test_detail_reads_operator_copy_but_keeps_business_plan_id(self):
        paths = []

        def fake_get(path, params=None, silent=False, timeout=None):
            paths.append(path)
            if "/simple/" in path:
                return _plan("plan:plan-0060@2", "2")
            return {"raw_payload": {"uuid": 123456}}

        with patch.object(asc, "_http_get_operator", side_effect=fake_get):
            detail = asc.get_plan_detail_operator("plan-0060")

        self.assertEqual(detail["plan_id"], "plan-0060")
        self.assertEqual(detail["resource_id"], "plan:plan-0060@2")
        self.assertTrue(all("plan:plan-0060@2" in path for path in paths))

    def test_operator_import_marks_nested_task_resources_only(self):
        body = {
            "resources": [{
                "resource_id": "plan:plan-0060",
                "task_type": "PLAN",
                "plan_id": "plan-0060",
                "stages": [{
                    "resource_id": "stage:stage-1",
                    "task_type": "STAGE",
                    "team_actions": [{
                        "car_actions": [{
                            "resource_id": "car_actions:ca-1",
                            "task_type": "CAR_ACTIONS",
                            "action_ids": ["action-1"],
                            "actions": [{
                                "resource_id": "action:action-1",
                                "task_type": "ACTION",
                                "action_id": "action-1",
                            }],
                        }],
                    }],
                }],
                "targets": [{"resource_id": "target:target-1", "task_type": "TARGET", "target_id": "target-1"}],
            }],
        }
        original = copy.deepcopy(body)

        prepared = dsc._prepare_operator_body("/api/v1/task_pool/ingestion/import", body)

        self.assertEqual(body, original)
        self.assertEqual(prepared["node_id"], "2")
        plan = prepared["resources"][0]
        self.assertEqual(plan["resource_id"], "plan:plan-0060@2")
        self.assertEqual(plan["plan_id"], "plan-0060")
        stage = plan["stages"][0]
        car_actions = stage["team_actions"][0]["car_actions"][0]
        action = car_actions["actions"][0]
        self.assertEqual(stage["resource_id"], "stage:stage-1@2")
        self.assertEqual(stage["node_id"], "2")
        self.assertEqual(car_actions["resource_id"], "car_actions:ca-1@2")
        self.assertEqual(action["resource_id"], "action:action-1@2")
        self.assertEqual(car_actions["action_ids"], ["action-1"])
        self.assertNotIn("node_id", plan["targets"][0])
        self.assertEqual(plan["targets"][0]["resource_id"], "target:target-1")

    def test_new_operator_plan_uses_node_cache_key(self):
        with patch.object(asc, "import_plan_to_operator", return_value={"ok": True}):
            saved = asc.create_operator_plan({"plan_id": "plan-0060", "title": "操控席副本"})
        self.assertEqual(saved["resource_id"], "plan:plan-0060@2")
        self.assertEqual(saved["plan_id"], "plan-0060")
        self.assertIsNotNone(task_pool.get("plan:plan-0060@2"))
        self.assertIsNone(task_pool.get("plan:plan-0060"))

    def test_operator_sync_does_not_overwrite_main_cache(self):
        task_pool.set("plan:plan-0060", {"plan_id": "plan-0060", "title": "主控", "_seat": "data_server"})
        task_pool.set("plan:plan-0060@2", {
            "plan_id": "plan-0060",
            "resource_id": "plan:plan-0060@2",
            "title": "操控席未同步",
            "stages": [],
            "_seat": "operator",
            "local_dirty": True,
        })
        imports = []

        def fake_post(path, body, silent=False, timeout=None):
            imports.append(body)
            return {"ok": True}

        with patch.object(asc, "_http_get_operator", return_value=None), \
             patch.object(asc, "_http_post_operator", side_effect=fake_post):
            self.assertTrue(asc.sync_plan_to_operator("plan-0060"))

        self.assertEqual(task_pool.get("plan:plan-0060")["title"], "主控")
        self.assertEqual(imports[0]["resources"][0]["resource_id"], "plan:plan-0060@2")
        self.assertEqual(imports[0]["resources"][0]["plan_id"], "plan-0060")
        self.assertFalse(task_pool.get("plan:plan-0060@2")["local_dirty"])


class TestNodeScopedCompletion(unittest.TestCase):
    def test_action_completion_uses_requested_node(self):
        plan = _plan("plan:plan-0060@2", "2")
        plan["stages"] = [{
            "stage_id": "stage-1",
            "team_actions": [{
                "team_id": "team-1",
                "car_actions": [{
                    "car_actions_id": "ca-1",
                    "vid": "equipment:ZD01",
                    "actions": [],
                    "action_ids": ["action-1"],
                }],
            }],
        }]
        calls = []

        def fake_query(http_get, task_type, node_id, limit):
            calls.append((task_type, node_id))
            if task_type == "CAR_ACTIONS":
                return [{
                    "car_actions_id": "ca-1",
                    "resource_id": "car_actions:ca-1@2",
                    "node_id": "2",
                    "actions": [],
                    "action_ids": ["action-1"],
                }]
            return [{
                "action_id": "action-1",
                "resource_id": "action:action-1@2",
                "node_id": "2",
                "action_type": "auto-move",
                "param": {"points": []},
            }]

        with patch.object(asc, "_query_resources_for_node", side_effect=fake_query):
            result = asc._build_car_actions_from_plan(plan, node_id="2")

        self.assertEqual(calls, [("CAR_ACTIONS", "2"), ("ACTION", "2")])
        self.assertEqual(result[0]["actions"][0]["resource_id"], "action:action-1@2")


if __name__ == "__main__":
    unittest.main()
