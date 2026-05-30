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

    # ---------- 写入存储 ----------
    for t in targets:
        task_pool.set(t["resource_id"], t)
    for r in resources:
        task_pool.set(r["resource_id"], r)

    print(f"[MockData] Loaded: {len(targets)} targets, {len(resources)} resources")
