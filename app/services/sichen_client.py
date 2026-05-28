"""
Sichen 火力规划小模型客户端
接口地址：http://25.11.1.101:28504
"""

import requests
from typing import Any, Dict, List, Optional

SICHEN_BASE_URL = "http://25.11.1.101:28504"


def call_plan_allocation(
    vehicles: List[Dict[str, Any]],
    targets: List[Dict[str, Any]],
    capability: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    调用 sichen /plan 接口进行火力分配。

    参数：
      vehicles: [{vehicle_id, platform_type, longitude, latitude, ammunition, faults}]
      targets:  [{target_id, name, type, center_position, object_level, threat, object_requirement_result}]
      capability: 可选，默认使用内置参数

    返回：
      sichen 响应的 JSON dict，含 vehicle_missions / report
      失败时返回 None
    """
    default_capability = {
        "weapons": {
            "FTK": {
                "range_max": 6000,
                "ammo_cost": 2000,
                "prep_time": 8.0,
                "fire_interval": 3.0,
                "base_prob": {"239": 0.95, "100": 0.9, "ground": 0.9},
            }
        },
        "platforms": {
            "light": {"max_speed": 60, "avg_speed": 40},
            "medium": {"max_speed": 80, "avg_speed": 55},
        },
        "req_prob_map": {
            "彻底摧毁": 0.90,
            "优先摧毁": 0.85,
            "摧毁": 0.80,
            "拦截": 0.70,
            "压制": 0.50,
            "侦察确认": 0.60,
        },
    }

    payload = {
        "vehicles_data": {"vehicles": vehicles},
        "targets_data": {
            "fixed_targets": targets,
            "moving_targets": [],
        },
        "capability": capability or default_capability,
        "weights": [0.6, 0.2, 0.2],
    }

    try:
        resp = requests.post(
            f"{SICHEN_BASE_URL}/plan",
            json=payload,
            timeout=15,
            proxies={"http": None, "https": None},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None
