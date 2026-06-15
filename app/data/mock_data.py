"""
预置 Mock 数据
包含杀伤链示例数据、资源池数据、态势目标数据
"""

from datetime import datetime, timezone


def preload_mock_data(task_pool):
    """启动时预置数据到内存存储"""

    # ---------- 态势目标 ----------
    targets = [
        {
            "resource_id": "target:target-1",
            "task_type": "TARGET",
            "target_id": "target-1",
            "target_name": "目标1",
            "target_type": "地面目标",
            "foe": "ENEMY",
            "threat_level": "high",
            "location": {"latitude": 39.8642, "longitude": 118.2085, "altitude": 95.0},
            "search_text": "目标1 地面目标 敌方",
        },
        {
            "resource_id": "target:target-2",
            "task_type": "TARGET",
            "target_id": "target-2",
            "target_name": "目标2",
            "target_type": "地面目标",
            "foe": "ENEMY",
            "threat_level": "medium",
            "location": {"latitude": 39.8701, "longitude": 118.2264, "altitude": 106.0},
            "search_text": "目标2 地面目标 敌方",
        },
    ]

    # ---------- 装备资源 ----------
    resources = [
        {
            "resource_id": "equipment:vehicle-A",
            "task_type": "EQUIPMENT",
            "entity_kind": "equipment",
            "resource_name": "无人车A",
            "resource_tag": "EQUIPMENT",
            "resource_type": "UGV",
            "online_status": "ONLINE",
            "capacity": {"max_range_km": 12, "max_speed_kmh": 45, "recon_range_km": 3},
            "search_text": "无人车A UGV 侦察",
        },
        {
            "resource_id": "equipment:vehicle-B",
            "task_type": "EQUIPMENT",
            "entity_kind": "equipment",
            "resource_name": "无人车B",
            "resource_tag": "EQUIPMENT",
            "resource_type": "UGV",
            "online_status": "ONLINE",
            "capacity": {"max_range_km": 12, "max_speed_kmh": 42, "strike_range_km": 4},
            "search_text": "无人车B UGV 打击",
        },
    ]

    # ---------- 路线/区域资源（供行动序列路线参数选择） ----------
    routes = [
        {
            "resource_id": "route:route-001",
            "task_type": "ROUTE",
            "title": "路线1",
            "description": "集结点至侦察阵位路线",
            "state": "READY",
            "points": [
                {"lon": 116.1278530, "lat": 39.7658100, "alt": 52.95, "attribute": "路网点"},
                {"lon": 116.1286534, "lat": 39.7662105, "alt": 53.20, "attribute": "路网点"},
                {"lon": 116.1294731, "lat": 39.7667975, "alt": 53.72, "attribute": "非路网点"},
                {"lon": 116.1249785, "lat": 39.7622797, "alt": 54.30, "attribute": "路网点"},
                {"lon": 116.1235196, "lat": 39.7606298, "alt": 55.50, "attribute": "路网点"},
            ],
            "search_text": "路线1 集结点至侦察阵位",
        },
        {
            "resource_id": "route:route-002",
            "task_type": "ROUTE",
            "title": "路线2",
            "description": "巡逻路线A",
            "state": "READY",
            "points": [
                {"lon": 116.1221466, "lat": 39.7587490, "alt": 56.79, "attribute": "路网点"},
                {"lon": 116.1208593, "lat": 39.7570660, "alt": 49.48, "attribute": "路网点"},
                {"lon": 116.1200012, "lat": 39.7559110, "alt": 49.74, "attribute": "非路网点"},
                {"lon": 116.1198724, "lat": 39.7542610, "alt": 50.04, "attribute": "路网点"},
            ],
            "search_text": "路线2 巡逻路线A",
        },
        {
            "resource_id": "route:route-003",
            "task_type": "ROUTE",
            "title": "路线3",
            "description": "通信中继路线",
            "state": "READY",
            "points": [
                {"lon": 116.1184994, "lat": 39.7521820, "alt": 50.50, "attribute": "路网点"},
                {"lon": 116.1176412, "lat": 39.7505649, "alt": 50.84, "attribute": "路网点"},
                {"lon": 116.1180703, "lat": 39.7501359, "alt": 50.89, "attribute": "路网点"},
                {"lon": 116.1172121, "lat": 39.7489148, "alt": 51.16, "attribute": "非路网点"},
                {"lon": 116.1181561, "lat": 39.7484857, "alt": 51.18, "attribute": "路网点"},
            ],
            "search_text": "路线3 通信中继路线",
        },
    ]

    areas = [
        {
            "resource_id": "area:area-001",
            "task_type": "AREA",
            "title": "区域A",
            "description": "目标侦察区域",
            "state": "READY",
            "polygon": [
                {"lon": 116.1300000, "lat": 39.7680000, "alt": 55.0},
                {"lon": 116.1320000, "lat": 39.7680000, "alt": 55.0},
                {"lon": 116.1320000, "lat": 39.7660000, "alt": 55.0},
                {"lon": 116.1300000, "lat": 39.7660000, "alt": 55.0},
            ],
            "search_text": "区域A 目标侦察区域",
        },
        {
            "resource_id": "area:area-002",
            "task_type": "AREA",
            "title": "区域B",
            "description": "巡逻警戒区域",
            "state": "READY",
            "polygon": [
                {"lon": 116.1250000, "lat": 39.7610000, "alt": 50.0},
                {"lon": 116.1270000, "lat": 39.7610000, "alt": 50.0},
                {"lon": 116.1270000, "lat": 39.7590000, "alt": 50.0},
                {"lon": 116.1250000, "lat": 39.7590000, "alt": 50.0},
            ],
            "search_text": "区域B 巡逻警戒区域",
        },
    ]

    # ---------- 行动序列调测方案（fake） ----------
    # 依据《装备行动序列知识.md》，包含全部车型及其支持的全部 action_type
    fake_plan = _build_fake_action_sequence_plan()
    task_pool.set(fake_plan["resource_id"], fake_plan)

    # ---------- 写入存储 ----------
    for t in targets:
        task_pool.set(t["resource_id"], t)
    for r in resources:
        task_pool.set(r["resource_id"], r)
    for route in routes:
        task_pool.set(route["resource_id"], route)
    for area in areas:
        task_pool.set(area["resource_id"], area)

    print(
        f"[MockData] Loaded: {len(targets)} targets, {len(resources)} resources, "
        f"{len(routes)} routes, {len(areas)} areas, 1 fake action-sequence plan"
    )


def _build_fake_action_sequence_plan():
    """构造包含所有车型/所有行动类型的 fake PLAN，用于行动序列参数弹窗调试。"""

    plan_id = "FAKE_ACTION_SEQUENCE_001"
    stage_id = "STAGE_FAKE_001"
    team_id = "TEAM_ALL"

    base_action = {
        "task_type": "ACTION",
        "plan_id": plan_id,
        "stage_id": stage_id,
        "team_id": team_id,
        "state": "SCHEDULED",
    }

    def move_action(aid, name, vid, seq):
        return {
            **base_action,
            "resource_id": f"action:{aid}",
            "action_id": aid,
            "name": name,
            "vid": vid,
            "action_seq": seq,
            "description": "沿指定目标点或路径进行自主机动",
            "action_type": "Auto-Move",
            "param": {
                "waypoints": [
                    {"lat": 39.75, "lon": 116.11, "alt": 51.4},
                    {"lat": 39.756, "lon": 116.118, "alt": 49.84},
                ],
                "speed": 20,
            },
        }

    def lens_action(aid, name, vid, seq):
        return {
            **base_action,
            "resource_id": f"action:{aid}",
            "action_id": aid,
            "name": name,
            "vid": vid,
            "action_seq": seq,
            "description": "使用白光侦察传感器对目标进行侦察",
            "action_type": "Lens-Recon",
            "param": {
                "target_id": "target_001",
                "target_name": "区域A",
                "type": 2,
                "recon_position": {"lon": 116.134131, "lat": 39.766476, "alt": 100.0},
                "azimuth_deg": 346.0,
                "fov_deg": 165.1,
                "move_time_s": 828.8,
                "scan_time_s": 55.0,
            },
        }

    def strike_action(aid, name, vid, seq, action_type):
        return {
            **base_action,
            "resource_id": f"action:{aid}",
            "action_id": aid,
            "name": name,
            "vid": vid,
            "action_seq": seq,
            "description": f"使用{action_type}载荷进行目标打击",
            "action_type": action_type,
            "param": {
                "target_id": "target_001",
                "target_name": "区域A",
                "fire_duration_s": 6,
                "fire_position": {"lon": 116.108, "lat": 39.749},
                "fire_mode": 1,
                "damage_mode": 1,
                "blank": 0,
                "planned_ammo": 10,
            },
        }

    def relay_action(aid, name, vid, seq, action_type):
        return {
            **base_action,
            "resource_id": f"action:{aid}",
            "action_id": aid,
            "name": name,
            "vid": vid,
            "action_seq": seq,
            "description": "与地面/空中通信载荷进行通信中继",
            "action_type": action_type,
            "param": {
                "duration_s": 900,
                "ip": "192.168.168.100",
                "type": 1,
            },
        }

    # 侦察打击无人车
    recon_strike_vid = "equipment:recon-strike-01"
    recon_strike_actions = [
        move_action("RS_MOVE", "自主机动", recon_strike_vid, 1),
        lens_action("RS_LENS", "光电侦察", recon_strike_vid, 2),
        strike_action("RS_40MM", "40mm机炮打击", recon_strike_vid, 3, "40mm-Gun-Launch"),
        {
            **base_action,
            "resource_id": "action:RS_SEARCH_SHOOT",
            "action_id": "RS_SEARCH_SHOOT",
            "name": "侦察打击",
            "vid": recon_strike_vid,
            "action_seq": 4,
            "description": "区域自主侦察，发现目标后立即自主打击",
            "action_type": "search-and-shoot",
            "param": {
                "target_id": "target_001",
                "target_name": "区域A",
                "time": 10.0,
            },
        },
    ]

    # 火力支援无人车
    fire_support_vid = "equipment:fire-support-01"
    fire_support_actions = [
        move_action("FS_MOVE", "自主机动", fire_support_vid, 1),
        lens_action("FS_LENS", "光电侦察", fire_support_vid, 2),
        strike_action("FS_GUN", "机枪打击", fire_support_vid, 3, "7.62mm-Gun-Shot"),
        strike_action("FS_AT", "反坦克导弹打击", fire_support_vid, 4, "AT-Missile-Launch"),
        strike_action("FS_ROCKET", "火箭弹打击", fire_support_vid, 5, "Rocket-Launch"),
        strike_action("FS_LOITER", "巡飞弹打击", fire_support_vid, 6, "Loitering-Munition-Launch"),
    ]

    # 巡逻无人车
    patrol_vid = "equipment:patrol-01"
    patrol_actions = [
        move_action("PT_MOVE", "自主机动", patrol_vid, 1),
        lens_action("PT_LENS", "光电侦察", patrol_vid, 2),
        strike_action("PT_GUN", "机枪打击", patrol_vid, 3, "7.62mm-Gun-Shot"),
    ]

    # 通信无人车
    comm_vid = "equipment:communication-01"
    comm_actions = [
        move_action("CM_MOVE", "自主机动", comm_vid, 1),
        relay_action("CM_LAND_RELAY", "地面通信中继", comm_vid, 2, "Land-Communication-Relay"),
        relay_action("CM_AIR_RELAY", "空中通信中继", comm_vid, 3, "Air-Communication-Relay"),
    ]

    return {
        "resource_id": f"plan:{plan_id}",
        "task_type": "PLAN",
        "plan_id": plan_id,
        "title": "行动序列参数调测方案",
        "description": "包含全部车型及其支持的全部行动类型，用于行动序列参数弹窗调试",
        "state": "DRAFT",
        "teams": [
            {
                "team_id": team_id,
                "name": "综合调测组",
                "description": "包含全部车型的调测编组",
                "state": "READY",
                "vehicles": [
                    {"vid": recon_strike_vid, "resource_type": "Recon-Strike-UGV"},
                    {"vid": fire_support_vid, "resource_type": "Fire-Support-UGV"},
                    {"vid": patrol_vid, "resource_type": "Patrol-UGV"},
                    {"vid": comm_vid, "resource_type": "Communication-UGV"},
                ],
            }
        ],
        "targets": [
            {
                "target_id": "target:AREA_A",
                "target_name": "区域A",
                "target_type": "区域",
                "description": "调测目标区域",
            }
        ],
        "stages": [
            {
                "stage_id": stage_id,
                "title": "全行动类型调测阶段",
                "stage_seq": 1,
                "description": "依次执行所有车型的全部行动类型",
                "team_ids": [team_id],
                "target_ids": ["target:AREA_A"],
                "state": "SCHEDULED",
                "team_actions": {
                    team_id: [
                        {
                            "vid": recon_strike_vid,
                            "state": "SCHEDULED",
                            "action_type": "",
                            "actions": recon_strike_actions,
                        },
                        {
                            "vid": fire_support_vid,
                            "state": "SCHEDULED",
                            "action_type": "",
                            "actions": fire_support_actions,
                        },
                        {
                            "vid": patrol_vid,
                            "state": "SCHEDULED",
                            "action_type": "",
                            "actions": patrol_actions,
                        },
                        {
                            "vid": comm_vid,
                            "state": "SCHEDULED",
                            "action_type": "",
                            "actions": comm_actions,
                        },
                    ]
                },
            }
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
