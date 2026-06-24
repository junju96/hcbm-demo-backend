#!/usr/bin/env python3
"""为火力、侦察、保障生成测试数据并导入数据服务器"""

import requests
import json

BASE_URL = "http://25.11.1.178:28801"

resources = [
    # ========== 火力 ==========
    {
        "task_type": "FIREPOWER",
        "resource_id": "firepower:fp-001",
        "resource_name": "远程火箭炮营",
        "quantity": 12,
        "weapon_type": "多管火箭炮",
        "ammo_status": "充足",
        "strike_range_km": 80,
        "lethality": {"effect_type": "面杀伤", "effect_value": "高爆燃烧"},
        "belonging_equipment": {"resource_id": "equipment:vehicle-A", "resource_name": "无人车A"},
    },
    {
        "task_type": "FIREPOWER",
        "resource_id": "firepower:fp-002",
        "resource_name": "巡飞弹集群",
        "quantity": 24,
        "weapon_type": "巡飞弹",
        "ammo_status": "待补充",
        "strike_range_km": 40,
        "lethality": {"effect_type": "精确打击", "effect_value": "穿甲破片"},
        "belonging_equipment": {"resource_id": "equipment:vehicle-B", "resource_name": "无人车B"},
    },
    {
        "task_type": "FIREPOWER",
        "resource_id": "firepower:fp-003",
        "resource_name": "迫击炮排",
        "quantity": 6,
        "weapon_type": "迫击炮",
        "ammo_status": "充足",
        "strike_range_km": 5,
        "lethality": {"effect_type": "曲射压制", "effect_value": "高爆破片"},
        "belonging_equipment": {"resource_id": "equipment:vehicle-C", "resource_name": "无人车C"},
    },
    # ========== 侦察 ==========
    {
        "task_type": "RECON",
        "resource_id": "recon:rc-001",
        "resource_name": "光电侦察吊舱",
        "recon_methods": ["光电成像", "红外热像"],
        "recon_range_km": 15,
        "online_status": "在线",
        "resource_platform": {"resource_id": "equipment:vehicle-A", "resource_name": "无人车A"},
        "coverage_focus": "区域B前沿阵地",
    },
    {
        "task_type": "RECON",
        "resource_id": "recon:rc-002",
        "resource_name": "合成孔径雷达",
        "recon_methods": ["SAR成像", "GMTI跟踪"],
        "recon_range_km": 30,
        "online_status": "待机",
        "resource_platform": {"resource_id": "equipment:vehicle-B", "resource_name": "无人车B"},
        "coverage_focus": "区域C纵深地带",
    },
    # ========== 保障 ==========
    {
        "task_type": "SUPPORT",
        "resource_id": "support:sp-001",
        "resource_name": "油料补给车",
        "support_unit": "后勤营油料连",
        "support_capability": "单次补给500升柴油，支持4台车辆同时加油",
        "current_status": "待命",
        "support_category": "油料保障",
        "mobility_capability": "公路机动",
        "deployment_location": {
            "location_name": "集结区域1",
            "latitude": "39.0092",
            "longitude": "116.3869",
            "altitude": 50,
        },
    },
    {
        "task_type": "SUPPORT",
        "resource_id": "support:sp-002",
        "resource_name": "野战维修组",
        "support_unit": "装备保障营维修连",
        "support_capability": "具备底盘、动力、光电、通信系统现场抢修能力",
        "current_status": "出动中",
        "support_category": "维修保障",
        "mobility_capability": "伴随机动",
        "deployment_location": {
            "location_name": "区域B南侧",
            "latitude": "39.0156",
            "longitude": "116.4023",
            "altitude": 65,
        },
    },
]

payload = {
    "resources": resources,
    "return_data_type": "typed",
    "ignore_errors": True,
}

print("准备导入测试资源：")
for r in resources:
    print(f"  [{r['task_type']}] {r['resource_id']}: {r.get('resource_name', 'N/A')}")

resp = requests.post(
    f"{BASE_URL}/api/v1/task_pool/ingestion/import",
    json=payload,
    timeout=10,
)

print(f"\n状态码: {resp.status_code}")
try:
    data = resp.json()
    print(f"响应: {json.dumps(data, ensure_ascii=False, indent=2)}")
except Exception as e:
    print(f"解析失败: {e}")
    print(f"原始响应: {resp.text[:500]}")

# 验证
print("\n验证导入结果...")
for tt in ['FIREPOWER', 'RECON', 'SUPPORT']:
    r = requests.post(
        f"{BASE_URL}/api/v1/task_pool/resources/query",
        json={"task_type": tt, "limit": 20},
        timeout=10,
    )
    if r.status_code == 200:
        items = r.json()
        print(f"  {tt}: {len(items)} 条")
    else:
        print(f"  {tt}: 查询失败 {r.status_code}")
