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
    """构造包含底盘/火力/侦打/巡逻/电磁全部元任务的 fake PLAN。

    约定：
      - action_type 统一全小写，按协议名称命名；
      - 不保留整车模式、自定义打击、通信中继车；
      - param 字段与协议 service 字段对齐，便于直接下发转换。
    """

    plan_id = "FAKE_ACTION_SEQUENCE_001"
    stage_id = "STAGE_FAKE_001"
    team_id = "TEAM_ALL"

    # 调测区域/目标坐标
    area_a = [
        {"lon": 116.1300000, "lat": 39.7680000, "alt": 55.0},
        {"lon": 116.1320000, "lat": 39.7680000, "alt": 55.0},
        {"lon": 116.1320000, "lat": 39.7660000, "alt": 55.0},
        {"lon": 116.1300000, "lat": 39.7660000, "alt": 55.0},
    ]

    target_point = {
        "target_ref": "target:target-1",
        "lon": 118.208500,
        "lat": 39.864200,
        "alt": 95.0,
        "tart": 6,
        "attr": 1,
        "thr": 80,
        "dam": 1,
        "blk": 2,
        "figt": 2,
        "sug": 3,
    }

    base_action = {
        "task_type": "ACTION",
        "plan_id": plan_id,
        "stage_id": stage_id,
        "team_id": team_id,
        "state": "SCHEDULED",
    }

    def action(aid, name, vid, seq, action_type, description, param):
        return {
            **base_action,
            "resource_id": f"action:{aid}",
            "action_id": aid,
            "name": name,
            "vid": vid,
            "action_seq": seq,
            "description": description,
            "action_type": action_type,
            "param": param,
        }

    # ---------- 底盘类 ----------
    chassis_vid = "equipment:chassis-01"
    path_points = [
        {"lon": 116.1278530, "lat": 39.7658100, "alt": 52.95, "radius": -1, "type": 1},
        {"lon": 116.1286534, "lat": 39.7662105, "alt": 53.20, "radius": -1, "type": 1},
        {"lon": 116.1294731, "lat": 39.7667975, "alt": 53.72, "radius": -1, "type": 2},
    ]
    formation_points = [
        {"lon": 116.1278530, "lat": 39.7658100, "alt": 52.95, "offsetX": 5, "offsetY": -3},
        {"lon": 116.1286534, "lat": 39.7662105, "alt": 53.20, "offsetX": 5, "offsetY": -3},
    ]
    chassis_actions = [
        action("CH_MOVE", "自主机动", chassis_vid, 1, "auto-move",
               "沿指定目标点或路径进行自主机动", {
                   "route_id": "route:route-001",
                   "points": path_points,
                   "limited_speed": 20,
                   "safe_mode": 0,
                   "loop_mode": 0,
               }),
        action("CH_FOLLOW", "跟随机动", chassis_vid, 2, "follow-move",
               "跟随目标进行机动", {
                   "x": 960,
                   "y": 540,
                   "width": 1920,
                   "height": 1080,
                   "distance": 10,
                   "limited_speed": 15,
                   "safe_mode": 0,
                   "strategy": 0,
               }),
        action("CH_SILENT", "静默值守", chassis_vid, 3, "silent-guard",
               "在指定位置静默值守", {
                   "time": 300,
               }),
        action("CH_SET_RETURN", "设置返航点", chassis_vid, 4, "set-return-point",
               "设置当前位置为返航点", {}),
        action("CH_RETURN", "开启返航", chassis_vid, 5, "return-to-base",
               "返回已设置的返航点", {}),
        action("CH_FORMATION", "编队机动", chassis_vid, 6, "formation-move",
               "按编队队形跟随头车机动", {
                   "points": formation_points,
                   "limited_speed": 18,
                   "formation_mode": 0,
                   "safe_mode": 0,
               }),
        action("CH_MANUAL", "人工任务", chassis_vid, 7, "manual-task",
               "人工介入任务", {
                   "type": 1,
               }),
        action("CH_POSE", "姿态调整", chassis_vid, 8, "pose-adjust",
               "调整车辆姿态", {
                   "pose": [9000, 0, 0],
                   "pose_deviation": [36100, 9100, 9100],
                   "limited_speed": 10,
                   "safe_mode": 0,
               }),
    ]

    # ---------- 火力车载荷 ----------
    fire_support_vid = "equipment:fire-support-01"
    fire_support_actions = [
        action("FS_LENS", "光电侦察", fire_support_vid, 1, "lens-recon",
               "使用白光/红外侦察传感器对目标区域进行侦察", {
                   "type": 2,
                   "mode": 3,
                   "time": 120,
                   "area_id": "area:area-001",
                   "area": area_a,
                   "direct": {
                       "type": 1,
                       "cent": 9000,
                       "sear": 6000,
                       "up": 3000,
                       "down": -1000,
                       "dist": 2000,
                       "sens": 0,
                   },
               }),
        action("FS_RECON_STRIKE", "侦察打击", fire_support_vid, 2, "recon-strike",
               "区域自主侦察，发现目标后立即自主打击", {
                   "time": 180,
                   "area_id": "area:area-001",
                   "area": area_a[:2],
               }),
        action("FS_GUN", "机枪打击", fire_support_vid, 3, "gun-shot",
               "使用机枪对目标点进行打击", {
                   "time": 30,
                   "sort": 1,
                   "num": 1,
                   "points": [target_point],
               }),
        action("FS_ROCKET", "火箭弹打击", fire_support_vid, 4, "rocket-launch",
               "使用火箭弹对目标点/区域进行打击", {
                   "type": 1,
                   "time": 60,
                   "sort": 1,
                   "num": 1,
                   "points": [target_point],
               }),
        action("FS_LOITER", "巡飞弹打击", fire_support_vid, 5, "loitering-munition-launch",
               "发射巡飞弹对目标点进行打击", {
                   "time": 60,
                   "sort": 1,
                   "num": 1,
                   "points": [target_point],
               }),
    ]

    # ---------- 侦打车载荷 ----------
    recon_strike_vid = "equipment:recon-strike-01"
    recon_strike_actions = [
        action("RS_LENS", "光电侦察", recon_strike_vid, 1, "lens-recon",
               "使用白光/红外侦察传感器对目标区域进行侦察", {
                   "type": 2,
                   "mode": 3,
                   "time": 120,
                   "area_id": "area:area-001",
                   "area": area_a,
                   "direct": {
                       "type": 1,
                       "cent": 9000,
                       "sear": 6000,
                       "up": 3000,
                       "down": -1000,
                       "dist": 2000,
                       "sens": 0,
                   },
               }),
        action("RS_RECON_STRIKE", "侦察打击", recon_strike_vid, 2, "recon-strike",
               "区域自主侦察，发现目标后立即自主打击", {
                   "time": 180,
                   "area_id": "area:area-001",
                   "area": area_a[:2],
               }),
        action("RS_40MM", "40炮打击", recon_strike_vid, 3, "40mm-gun-launch",
               "使用40炮对目标点进行打击", {
                   "time": 45,
                   "sort": 1,
                   "num": 1,
                   "points": [target_point],
               }),
        action("RS_AT", "红箭13导弹打击", recon_strike_vid, 4, "at-missile-launch",
               "使用红箭13反坦克导弹对目标点进行打击", {
                   "time": 60,
                   "sort": 1,
                   "num": 1,
                   "points": [{**target_point, "alt": 2100}],
               }),
        action("RS_GUN", "机枪打击", recon_strike_vid, 5, "gun-shot",
               "使用机枪对目标点进行打击", {
                   "time": 30,
                   "sort": 1,
                   "num": 1,
                   "points": [target_point],
               }),
        action("RS_LASER", "激光照射", recon_strike_vid, 6, "laser-illumination",
               "对目标点进行激光照射引导", {
                   "time": 120,
                   "act": 1,
                   "param1": 0,
                   "param2": 0,
                   "ene": 80,
                   "freq": 1000,
                   "meat": 30,
                   "delay": 5,
                   "max": 10,
                   "type": 1,
                   "strategy": 0,
                   "lon": 116.407000,
                   "lat": 39.904000,
                   "alt": 2100,
               }),
    ]

    # ---------- 巡逻车载荷 ----------
    patrol_vid = "equipment:patrol-01"
    patrol_actions = [
        action("PT_LENS", "光电侦察", patrol_vid, 1, "lens-recon",
               "使用白光/红外侦察传感器对目标区域进行侦察", {
                   "type": 2,
                   "mode": 3,
                   "time": 120,
                   "area_id": "area:area-001",
                   "area": area_a,
                   "direct": {
                       "type": 1,
                       "cent": 9000,
                       "sear": 6000,
                       "up": 3000,
                       "down": -1000,
                       "dist": 2000,
                       "sens": 0,
                   },
               }),
        action("PT_RECON_STRIKE", "巡逻车侦察打击", patrol_vid, 2, "recon-strike",
               "区域巡逻侦察并打击发现目标", {
                   "time": 180,
                   "tarty": 6,
                   "attr": 1,
                   "thr": 80,
                   "dam": 1,
                   "blk": 2,
                   "figt": 2,
                   "sug": 3,
                   "ammo": 10,
                   "strategy": 0,
                   "area_id": "area:area-001",
                   "area": area_a[:2],
               }),
        action("PT_GUN", "机枪打击", patrol_vid, 3, "gun-shot",
               "使用机枪对目标点进行打击", {
                   "time": 30,
                   "sort": 1,
                   "num": 1,
                   "points": [target_point],
               }),
        action("PT_ACOUSTIC", "强声拒止", patrol_vid, 4, "acoustic-deterrence",
               "对目标区域实施强声拒止", {
                   "time": 60,
                   "tarty": 1,
                   "attr": 2,
                   "thr": 50,
                   "dam": 0,
                   "blk": 0,
                   "figt": 0,
                   "sug": 0,
                   "ammo": 0,
                   "strategy": 0,
                   "area_id": "area:area-001",
                   "area": area_a[:1],
               }),
        action("PT_LIGHT", "强光拒止", patrol_vid, 5, "light-deterrence",
               "对目标区域实施强光拒止", {
                   "time": 60,
                   "tarty": 1,
                   "attr": 2,
                   "thr": 50,
                   "dam": 0,
                   "blk": 0,
                   "figt": 0,
                   "sug": 0,
                   "ammo": 0,
                   "strategy": 0,
                   "area_id": "area:area-001",
                   "area": area_a[:1],
               }),
    ]

    # ---------- 空地车载荷 ----------
    air_ground_vid = "equipment:air-ground-01"
    air_recon_point = {
        "lon": 116.391000,
        "lat": 39.907000,
        "alt": 100.0,
        "type": 0,
        "speed": 150,
        "camera": 2,
        "gimpitch": 36100,
        "gimyaw": 36100,
        "action": 1,
        "playaw": 36100,
        "zoom": 10,
        "loiter": 0,
    }
    air_ground_actions = [
        action("AG_AIR_RECON", "空中侦察", air_ground_vid, 1, "air-recon",
               "空中平台对指定区域/点实施侦察", {
                   "type": 2,
                   "mode": 1,
                   "time": 120,
                   "points1": [air_recon_point],
                   "points2": [],
                   "points3": [],
               }),
    ]

    # ---------- 电磁车载荷 ----------
    electronic_vid = "equipment:electronic-01"
    frequency = [{"start": 30000000, "end": 18000000000}]
    protect = {
        "ckl_dp": "30.0,100.0",
        "ckl_tp": "100.0,200.0",
        "zzw_dp": "400.0,500.0",
        "zzw_tp": "500.0,600.0",
        "xtl_tp": "700.0,800.0",
        "xtl_dp": "800.0,900.0",
    }
    electronic_actions = [
        action("EL_RECON", "电磁侦察", electronic_vid, 1, "electronic-recon",
               "对目标区域实施电磁频谱侦察", {
                   "mode": 3,
                   "time": 300,
                   "num": 1,
                   "freqtype": 62,
                   "frequency": frequency,
                   "area_id": "area:area-001",
                   "area": area_a,
                   "direct": {
                       "type": 1,
                       "cent": 9000,
                       "sear": 6000,
                       "up": 3000,
                       "down": -1000,
                       "dist": 2000,
                       "sens": 0,
                   },
               }),
        action("EL_JAM", "电磁突击", electronic_vid, 2, "electronic-jamming",
               "对目标区域实施电磁干扰压制", {
                   "mode": 3,
                   "time": 300,
                   "sort": 1,
                   "num": 1,
                   "freqtype": 62,
                   "frequency": frequency,
                   "area_id": "area:area-001",
                   "area": area_a,
                   "direct": {
                       "type": 1,
                       "cent": 9000,
                       "sear": 6000,
                       "up": 3000,
                       "down": -1000,
                       "dist": 2000,
                       "sens": 0,
                   },
                   "protect": protect,
               }),
        action("EL_SILENT", "载荷静默", electronic_vid, 3, "payload-silent",
               "载荷进入静默状态", {
                   "time": 300,
               }),
    ]

    return {
        "resource_id": f"plan:{plan_id}",
        "task_type": "PLAN",
        "plan_id": plan_id,
        "title": "行动序列参数调测方案",
        "description": "包含底盘、火力、侦打、巡逻、电磁、空地六类车型的全部协议元任务（不含整车模式、自定义打击、通信中继车）",
        "state": "DRAFT",
        "teams": [
            {
                "team_id": team_id,
                "name": "综合调测组",
                "description": "包含底盘、火力、侦打、巡逻、电磁、空地六类车型的调测编组",
                "state": "READY",
                "vehicles": [
                    {"vid": chassis_vid, "resource_type": "Chassis-UGV"},
                    {"vid": fire_support_vid, "resource_type": "Fire-Support-UGV"},
                    {"vid": recon_strike_vid, "resource_type": "Recon-Strike-UGV"},
                    {"vid": patrol_vid, "resource_type": "Patrol-UGV"},
                    {"vid": electronic_vid, "resource_type": "Electronic-UGV"},
                    {"vid": air_ground_vid, "resource_type": "Air-Ground-UAV"},
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
                "description": "依次执行所有车型支持的全部协议元任务（含空地车空中侦察）",
                "team_ids": [team_id],
                "target_ids": ["target:AREA_A"],
                "state": "SCHEDULED",
                "team_actions": {
                    team_id: [
                        {"vid": chassis_vid, "state": "SCHEDULED", "action_type": "", "actions": chassis_actions},
                        {"vid": fire_support_vid, "state": "SCHEDULED", "action_type": "", "actions": fire_support_actions},
                        {"vid": recon_strike_vid, "state": "SCHEDULED", "action_type": "", "actions": recon_strike_actions},
                        {"vid": patrol_vid, "state": "SCHEDULED", "action_type": "", "actions": patrol_actions},
                        {"vid": electronic_vid, "state": "SCHEDULED", "action_type": "", "actions": electronic_actions},
                        {"vid": air_ground_vid, "state": "SCHEDULED", "action_type": "", "actions": air_ground_actions},
                    ]
                },
            }
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
