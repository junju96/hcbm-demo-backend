# -*- coding: utf-8 -*-
"""打击/侦察目标解析测试 — 按 0713 §10 把 UI/DS 结构映射为协调卡字段

覆盖：
- 打击类：param.points（协调卡）→ param.targets[]（参考软件/DS）→ param.target.location
- 侦察类：param.area → param.area_points → param.target.location
- 区域目标（location 多顶点）按顶点序列展开，num 按点数重算
"""
import unittest

from app.services import action_sequence_client as asc


class ResolveStrikePointsTest(unittest.TestCase):
    def test_points_kept_as_is(self):
        points = [{"lon": 116.1, "lat": 39.7, "alt": 10, "tart": 6}]
        self.assertEqual(asc._resolve_strike_points({"points": points}), points)

    def test_targets_single_location_vertex(self):
        param = {
            "targets": [
                {
                    "target_id": "target_1",
                    "name": "点位1",
                    "location": [{"longitude": 116.1, "latitude": 39.7, "altitude": 10}],
                }
            ]
        }
        self.assertEqual(
            asc._resolve_strike_points(param),
            [{"lon": 116.1, "lat": 39.7, "alt": 10}],
        )

    def test_targets_region_expanded_to_vertices(self):
        param = {
            "targets": [
                {
                    "target_id": "target_2",
                    "name": "区域C",
                    "location": [
                        {"longitude": 116.1, "latitude": 39.7, "altitude": 0},
                        {"longitude": 116.2, "latitude": 39.7, "altitude": 0},
                        {"longitude": 116.2, "latitude": 39.8, "altitude": 0},
                        {"longitude": 116.1, "latitude": 39.8, "altitude": 0},
                    ],
                }
            ]
        }
        points = asc._resolve_strike_points(param)
        self.assertEqual(len(points), 4)
        self.assertEqual(points[0], {"lon": 116.1, "lat": 39.7, "alt": 0})

    def test_targets_flat_lon_lat(self):
        param = {"targets": [{"target_id": "t", "lon": 116.1, "lat": 39.7, "altitude": 5, "dam": 1}]}
        self.assertEqual(
            asc._resolve_strike_points(param),
            [{"lon": 116.1, "lat": 39.7, "alt": 5, "dam": 1}],
        )

    def test_target_location_fallback(self):
        param = {"target": {"target_id": "t", "location": [
            {"longitude": 116.1, "latitude": 39.7, "altitude": 0},
        ]}}
        self.assertEqual(len(asc._resolve_strike_points(param)), 1)

    def test_empty(self):
        self.assertEqual(asc._resolve_strike_points({}), [])
        self.assertEqual(asc._resolve_strike_points({"targets": []}), [])

    def test_points_take_precedence_over_targets(self):
        param = {
            "points": [{"lon": 1.0, "lat": 2.0, "alt": 0}],
            "targets": [{"location": [{"longitude": 3.0, "latitude": 4.0, "altitude": 0}]}],
        }
        self.assertEqual(asc._resolve_strike_points(param), [{"lon": 1.0, "lat": 2.0, "alt": 0}])


class ResolveAreaPointsTest(unittest.TestCase):
    def test_area_kept(self):
        area = [{"lon": 116.1, "lat": 39.7, "alt": 0}]
        self.assertEqual(asc._resolve_area_points({"area": area}), area)

    def test_area_points_fallback(self):
        param = {"area": [], "area_points": [
            {"longitude": 116.1, "latitude": 39.7, "altitude": 10},
            {"longitude": 116.2, "latitude": 39.8, "altitude": 10},
        ]}
        self.assertEqual(len(asc._resolve_area_points(param)), 2)

    def test_target_location_fallback(self):
        param = {"target": {"location": [{"longitude": 116.1, "latitude": 39.7, "altitude": 0}]}}
        self.assertEqual(len(asc._resolve_area_points(param)), 1)

    def test_empty(self):
        self.assertEqual(asc._resolve_area_points({}), [])


class BuildServiceFromTargetsTest(unittest.TestCase):
    def test_machine_gun_uses_targets_and_recomputes_num(self):
        action = {
            "action_type": "machine-gun-strike",
            "name": "机枪打击",
            "param": {
                "time": 60,
                "sort": 1,
                "num": 1,
                "targets": [{
                    "target_id": "target_2",
                    "name": "区域C",
                    "location": [
                        {"longitude": 116.1, "latitude": 39.7, "altitude": 0},
                        {"longitude": 116.2, "latitude": 39.7, "altitude": 0},
                        {"longitude": 116.2, "latitude": 39.8, "altitude": 0},
                    ],
                }],
            },
        }
        service = asc._build_service_from_action(action, "patrol")
        self.assertEqual(service["sid"], 53)
        self.assertEqual(len(service["points"]), 3)
        self.assertEqual(service["num"], 3)
        self.assertEqual(service["points"][0]["lon"], 116100000)
        self.assertEqual(service["points"][0]["lat"], 39700000)

    def test_rocket_keeps_type_field(self):
        action = {
            "action_type": "rocket-strike",
            "name": "火箭弹打击",
            "param": {
                "time": 60, "sort": 1, "num": 1, "type": 2,
                "targets": [{"location": [{"longitude": 116.1, "latitude": 39.7, "altitude": 0}]}],
            },
        }
        service = asc._build_service_from_action(action, "fire_support")
        self.assertEqual(service["sid"], 23)
        self.assertEqual(service["type"], 2)
        self.assertEqual(len(service["points"]), 1)

    def test_lens_recon_uses_area_points(self):
        action = {
            "action_type": "lens-recon",
            "name": "光电侦察",
            "param": {
                "type": 3, "mode": 3, "time": 120,
                "area_points": [
                    {"longitude": 116.1, "latitude": 39.7, "altitude": 10},
                    {"longitude": 116.2, "latitude": 39.8, "altitude": 10},
                ],
            },
        }
        service = asc._build_service_from_action(action, "patrol")
        self.assertEqual(service["sid"], 51)
        self.assertEqual(len(service["area"]), 2)
        self.assertEqual(service["area"][0]["lon"], 116100000)

    def test_no_target_keeps_empty_points(self):
        service = asc._build_service_from_action(
            {"action_type": "machine-gun-strike", "param": {}}, "patrol"
        )
        self.assertEqual(service["points"], [])


if __name__ == "__main__":
    unittest.main()


class ZeroPlaceholderTest(unittest.TestCase):
    """「打开弹窗后保存」产生的全 0 占位不能遮蔽真实坐标。"""

    def test_zero_points_fall_back_to_targets(self):
        param = {
            "points": [{"lon": 0, "lat": 0, "alt": 0}],
            "targets": [{"location": [{"longitude": 116.1, "latitude": 39.7, "altitude": 0}]}],
        }
        points = asc._resolve_strike_points(param)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["lon"], 116.1)

    def test_zero_area_falls_back_to_area_points(self):
        param = {
            "area": [{"lon": 0, "lat": 0, "alt": 0}, {"lon": 0, "lat": 0, "alt": 0}],
            "area_points": [{"longitude": 116.1, "latitude": 39.7, "altitude": 0}],
        }
        points = asc._resolve_area_points(param)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["longitude"], 116.1)


class Legacy0912ParamsTest(unittest.TestCase):
    """0912 文档字段：target.waypoints / fire_position / fire_duration_s / speed。"""

    def test_auto_move_waypoints_and_speed(self):
        action = {
            "action_type": "auto-move",
            "param": {
                "target": {
                    "target_id": "route_001",
                    "target_name": "路线001",
                    "waypoints": [
                        {"lat": 39.75, "lon": 116.11, "alt": 51.4},
                        {"lat": 39.756, "lon": 116.118, "alt": 49.84},
                    ],
                },
                "speed": 30,
            },
        }
        service = asc._build_service_from_action(action, "recon_strike")
        self.assertEqual(service["sid"], 1)
        self.assertEqual(len(service["points"]), 2)
        self.assertEqual(service["limited_speed"], 30)
        self.assertEqual(service["points"][0]["lon"], 116110000)

    def test_machine_gun_fire_position_and_duration(self):
        action = {
            "action_type": "machine-gun-strike",
            "param": {
                "target": {"target_id": "target_001", "target_name": "区域A"},
                "fire_duration_s": 6,
                "fire_position": {"lon": 116.108, "lat": 39.749},
                "fire_mode": 1,
                "damage_mode": 1,
                "blank": 0,
                "planned_ammo": 10,
            },
        }
        service = asc._build_service_from_action(action, "patrol")
        self.assertEqual(service["sid"], 53)
        self.assertEqual(service["time"], 6)
        self.assertEqual(len(service["points"]), 1)
        self.assertEqual(service["points"][0]["lon"], 116108000)

    def test_sound_expel_fire_position_and_duration(self):
        action = {
            "action_type": "sound-expel",
            "param": {
                "target": {"target_id": "target_001", "target_name": "区域A"},
                "fire_position": {"lon": 116.108, "lat": 39.749},
                "fire_duration_s": 60,
            },
        }
        service = asc._build_service_from_action(action, "patrol")
        self.assertEqual(service["sid"], 54)
        self.assertEqual(service["time"], 60)
        self.assertEqual(len(service["area"]), 1)


class ProjectionSyncTest(unittest.TestCase):
    """保存时把协调卡字段镜像到 DS 投影字段，保证「保存后重新打开」能读回。"""

    def test_area_mirrors_to_area_points(self):
        synced = asc._sync_projection_param_fields(
            {"area": [{"lon": 116.1, "lat": 39.7, "alt": 0}]}
        )
        self.assertEqual(
            synced["area_points"],
            [{"longitude": 116.1, "latitude": 39.7, "altitude": 0}],
        )

    def test_zero_area_uses_target_location(self):
        synced = asc._sync_projection_param_fields({
            "area": [{"lon": 0, "lat": 0, "alt": 0}],
            "target": {"location": [{"longitude": 116.1, "latitude": 39.7, "altitude": 0}]},
        })
        self.assertEqual(synced["area_points"][0]["longitude"], 116.1)

    def test_zero_area_does_not_create_area_points(self):
        synced = asc._sync_projection_param_fields({"area": [{"lon": 0, "lat": 0, "alt": 0}]})
        self.assertNotIn("area_points", synced)

    def test_points_mirror_to_single_target_location(self):
        synced = asc._sync_projection_param_fields({
            "points": [{"lon": 116.1, "lat": 39.7, "alt": 0}],
            "targets": [{"target_id": "target_1", "location": []}],
        })
        self.assertEqual(
            synced["targets"][0]["location"],
            [{"longitude": 116.1, "latitude": 39.7, "altitude": 0}],
        )
        self.assertEqual(synced["targets"][0]["target_id"], "target_1")

    def test_multiple_targets_left_untouched(self):
        synced = asc._sync_projection_param_fields({
            "points": [{"lon": 116.1, "lat": 39.7, "alt": 0}],
            "targets": [{"location": []}, {"location": []}],
        })
        self.assertEqual(synced["targets"][0]["location"], [])
        self.assertEqual(synced["targets"][1]["location"], [])


class AirReconTypeTest(unittest.TestCase):
    """DS 侧 action_type 为 UAV-Air-Recon，必须解析到 sid=71。"""

    def test_resolve_sid_for_uav_air_recon(self):
        self.assertEqual(asc._resolve_sid("air_ground", "UAV-Air-Recon"), 71)

    def test_build_service_keeps_air_recon_fields(self):
        service = asc._build_service_from_action({
            "action_type": "UAV-Air-Recon",
            "name": "空中侦察",
            "param": {
                "service": {
                    "sid": 71,
                    "type": 1,
                    "mode": 2,
                    "points1": [{"lon": 116.1, "lat": 39.7, "alt": 500}],
                },
                "scan_time_s": 55,
                "move_time_s": 828.8,
            },
        }, "air_ground")
        self.assertEqual(service["sid"], 71)
        self.assertEqual(service["type"], 1)
        self.assertEqual(service["mode"], 2)
        self.assertEqual(service["time"], 884)
        self.assertEqual(len(service["points1"]), 1)

    def test_air_recon_time_rounds_half_up(self):
        service = asc._build_service_from_action({
            "action_type": "UAV-Air-Recon",
            "param": {"scan_time_s": 55.5},
        }, "air_ground")
        self.assertEqual(service["time"], 56)

    def test_air_recon_time_prefers_explicit_value(self):
        service = asc._build_service_from_action({
            "action_type": "UAV-Air-Recon",
            "param": {"time": 90, "scan_time_s": 55, "move_time_s": 828.8},
        }, "air_ground")
        self.assertEqual(service["time"], 90)

    def test_machine_gun_capitalized_type(self):
        service = asc._build_service_from_action({
            "action_type": "Machine-Gun-Strike",
            "param": {"targets": [{"location": [{"longitude": 116.1, "latitude": 39.7, "altitude": 0}]}]},
        }, "patrol")
        self.assertEqual(service["sid"], 53)
        self.assertEqual(len(service["points"]), 1)
