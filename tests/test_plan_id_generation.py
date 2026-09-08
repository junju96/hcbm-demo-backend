# -*- coding: utf-8 -*-
"""plan id 顺序编号策略测试 — plan-六位数字（现有数字后缀最大值 +1）"""
import unittest
from unittest.mock import patch

from app.services import action_sequence_client as asc
from app.services.task_pool import task_pool


class TestNextSequentialPlanId(unittest.TestCase):
    def test_empty_gives_first_id(self):
        self.assertEqual(asc._next_sequential_plan_id([]), "plan-000001")

    def test_max_suffix_plus_one(self):
        ids = ["plan-0001", "plan-0003", "plan-0002"]
        self.assertEqual(asc._next_sequential_plan_id(ids), "plan-000004")

    def test_ignores_non_sequential_ids(self):
        ids = ["PLAN_1757234567890", "kill-chain-1", "", None]
        self.assertEqual(asc._next_sequential_plan_id(ids), "plan-000001")

    def test_case_insensitive_prefix(self):
        self.assertEqual(asc._next_sequential_plan_id(["PLAN-000009"]), "plan-000010")

    def test_beyond_six_digits_keeps_growing(self):
        self.assertEqual(asc._next_sequential_plan_id(["plan-999999"]), "plan-1000000")


class TestGenerateOperatorPlanId(unittest.TestCase):
    def setUp(self):
        task_pool.clear()

    def tearDown(self):
        task_pool.clear()

    def test_combines_local_pool_and_operator_ds(self):
        task_pool.set("plan:plan-0002", {"task_type": "PLAN", "plan_id": "plan-0002"})
        with patch.object(asc, "query_plans_operator", return_value=[{"plan_id": "plan-0005"}]):
            self.assertEqual(asc._generate_operator_plan_id(), "plan-000006")

    def test_ds_unreachable_falls_back_to_local_pool(self):
        task_pool.set("plan:plan-0007", {"task_type": "PLAN", "plan_id": "plan-0007"})
        with patch.object(asc, "query_plans_operator", side_effect=ConnectionError("down")):
            self.assertEqual(asc._generate_operator_plan_id(), "plan-000008")


class TestCreateOperatorPlanIdFallback(unittest.TestCase):
    def setUp(self):
        task_pool.clear()

    def tearDown(self):
        task_pool.clear()

    def test_generates_sequential_id_when_missing(self):
        with patch.object(asc, "query_plans_operator", return_value=[{"plan_id": "plan-0001"}]), \
             patch.object(asc, "import_plan_to_operator", return_value=None):
            saved = asc.create_operator_plan({"title": "测试方案"})
        self.assertEqual(saved["plan_id"], "plan-000002")
        self.assertEqual(saved["resource_id"], "plan:plan-000002")

    def test_keeps_frontend_provided_id(self):
        with patch.object(asc, "import_plan_to_operator", return_value=None):
            saved = asc.create_operator_plan({"plan_id": "plan-000042", "title": "测试方案"})
        self.assertEqual(saved["plan_id"], "plan-000042")


class TestCreateCoordinationPlan(unittest.TestCase):
    """协同席 — 新建空方案（仅标题，无行动序列数据）"""

    def setUp(self):
        task_pool.clear()

    def tearDown(self):
        task_pool.clear()

    def test_generates_sequential_id_when_missing(self):
        with patch.object(asc, "query_plans", return_value=[{"plan_id": "plan-0007"}]), \
             patch.object(asc, "_import_plan_payload", return_value=True) as mock_import:
            saved = asc.create_coordination_plan({"title": "空方案"})
        self.assertEqual(saved["plan_id"], "plan-000008")
        self.assertEqual(saved["resource_id"], "plan:plan-000008")
        self.assertFalse(saved["local_dirty"])
        mock_import.assert_called_once()

    def test_keeps_frontend_provided_id(self):
        with patch.object(asc, "_import_plan_payload", return_value=True):
            saved = asc.create_coordination_plan({"plan_id": "plan-000042", "title": "空方案"})
        self.assertEqual(saved["plan_id"], "plan-000042")

    def test_marks_dirty_when_import_fails(self):
        with patch.object(asc, "_import_plan_payload", side_effect=ConnectionError("down")):
            saved = asc.create_coordination_plan({"plan_id": "plan-000010", "title": "空方案"})
        self.assertTrue(saved["local_dirty"])
        # 本地缓存仍可用（数据服务器恢复后由 sync 补偿）
        self.assertEqual(task_pool.get("plan:plan-000010")["title"], "空方案")


if __name__ == "__main__":
    unittest.main()
