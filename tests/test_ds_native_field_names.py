# -*- coding: utf-8 -*-
"""_to_ds_native_field_names 测试 — 前端/本地命名写回 DS 前转为 DS 原生命名

背景（2026-09-07 踩坑）：DS 的 TEAM 类型只认 team_name/team_equipments，
ACTION 只认 action_name；用本地命名（name/vehicles）import 时 DS 会生成
默认名（编组-XXX / 行动-action-XXXX）并丢掉 team_equipments。
"""
import unittest

from app.services import action_sequence_client as asc


class TestToDsNativeFieldNames(unittest.TestCase):
    def test_team_local_names_converted(self):
        plan = {"teams": [{"team_id": "t1", "name": "侦察组", "description": "d",
                           "vehicles": [{"vid": "equipment:ZD01"}]}]}
        out = asc._to_ds_native_field_names(plan)
        team = out["teams"][0]
        self.assertEqual(team["team_name"], "侦察组")
        self.assertEqual(team["team_description"], "d")
        self.assertEqual(team["team_equipments"], [{"vid": "equipment:ZD01"}])

    def test_team_ds_native_unchanged(self):
        plan = {"teams": [{"team_id": "t1", "team_name": "侦察组",
                           "team_equipments": [{"vid": "equipment:ZD01"}]}]}
        out = asc._to_ds_native_field_names(plan)
        team = out["teams"][0]
        self.assertEqual(team["team_name"], "侦察组")
        self.assertEqual(team["team_equipments"], [{"vid": "equipment:ZD01"}])

    def test_ds_native_wins_over_local_when_both_present(self):
        plan = {"teams": [{"team_id": "t1", "team_name": "正确名", "name": "旧名"}]}
        out = asc._to_ds_native_field_names(plan)
        self.assertEqual(out["teams"][0]["team_name"], "正确名")

    def test_action_local_name_converted(self):
        plan = {"stages": [{"stage_id": "s1", "team_actions": [
            {"team_id": "t1", "car_actions": [
                {"vid": "equipment:ZD01", "actions": [
                    {"action_id": "a1", "action_seq": 1, "name": "自主机动", "description": "d", "param": {}},
                ]}]}]}]}
        out = asc._to_ds_native_field_names(plan)
        action = out["stages"][0]["team_actions"][0]["car_actions"][0]["actions"][0]
        self.assertEqual(action["action_name"], "自主机动")
        self.assertEqual(action["action_description"], "d")

    def test_action_ds_native_name_preserved(self):
        plan = {"stages": [{"stage_id": "s1", "team_actions": [
            {"team_id": "t1", "car_actions": [
                {"vid": "equipment:ZD01", "actions": [
                    {"action_id": "a1", "action_seq": 1, "action_name": "自主机动", "param": {}},
                ]}]}]}]}
        out = asc._to_ds_native_field_names(plan)
        action = out["stages"][0]["team_actions"][0]["car_actions"][0]["actions"][0]
        self.assertEqual(action["action_name"], "自主机动")

    def test_plan_title_and_other_fields_untouched(self):
        plan = {"plan_id": "p1", "title": "方案A", "state": "DRAFT"}
        out = asc._to_ds_native_field_names(plan)
        self.assertEqual(out["title"], "方案A")
        self.assertEqual(out["state"], "DRAFT")

    def test_does_not_mutate_input(self):
        plan = {"teams": [{"team_id": "t1", "name": "侦察组"}]}
        asc._to_ds_native_field_names(plan)
        self.assertNotIn("team_name", plan["teams"][0])


if __name__ == "__main__":
    unittest.main()
