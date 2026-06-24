#!/usr/bin/env python3
"""生成并导入测试杀伤链数据到数据服务器"""

import requests
import json

BASE_URL = "http://25.11.1.178:28801"

def make_killchain(kcid, title, description, state, target_id, operation_list, assigned=False):
    """生成一条杀伤链数据"""
    raw_entries = []
    assigned_entries = []
    
    resource_ids = ["eq_无人车A", "eq_巡逻无人机", "eq_无人车B", target_id]
    
    for i, op in enumerate(operation_list, 1):
        # RAW entry
        if op == "侦察":
            options = [
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": False, "note": "光电侦察"},
                {"executor_id": "eq_巡逻无人机", "allocation_count": 1, "locked": False, "note": "空中侦察"},
            ]
        elif op == "定位":
            options = [
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": False, "note": "GPS定位"},
            ]
        elif op == "跟踪":
            options = [
                {"executor_id": "eq_巡逻无人机", "allocation_count": 1, "locked": False, "note": "持续跟踪"},
            ]
        elif op == "瞄准/引导":
            options = [
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": False, "note": "激光照射"},
            ]
        elif op == "打击":
            options = [
                {"executor_id": "eq_无人车B", "allocation_count": 2, "locked": False, "note": "主炮打击"},
            ]
        elif op == "评估":
            options = [
                {"executor_id": "eq_巡逻无人机", "allocation_count": 1, "locked": False, "note": "毁伤评估"},
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": False, "note": "抵近观察"},
            ]
        elif op == "干扰":
            options = [
                {"executor_id": "eq_无人车B", "allocation_count": 1, "locked": False, "note": "电子干扰"},
            ]
        elif op == "封锁":
            options = [
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": False, "note": "路口封锁"},
                {"executor_id": "eq_无人车B", "allocation_count": 1, "locked": False, "note": "火力封锁"},
            ]
        else:
            options = []
        
        raw_entry = {
            "entry_id": f"entry_{kcid[-3:]}_{i:02d}",
            "phase": "RAW",
            "entry_seq": i,
            "target_ids": [target_id],
            "operation": op,
            "executor_options": options,
            "selected_executor": None,
            "locked": False,
            "is_valid": True,
            "notes": f"{op}阶段说明",
        }
        raw_entries.append(raw_entry)
        
        # ASSIGNED entry（如果要求已分配）
        if assigned and options:
            sel = options[0]["executor_id"]
            assigned_entry = {
                "entry_id": f"entry_{kcid[-3:]}_{i:02d}",
                "phase": "ASSIGNED",
                "entry_seq": i,
                "target_ids": [target_id],
                "operation": op,
                "executor_options": [{
                    **options[0],
                    "locked": True,
                    "note": f"已选定-{options[0]['note']}"
                }],
                "selected_executor": sel,
                "locked": True,
                "is_valid": True,
                "notes": f"已分配：{sel}",
            }
            assigned_entries.append(assigned_entry)
    
    return {
        "task_type": "KILL_CHAIN",
        "kill_chain_id": kcid,
        "title": title,
        "description": description,
        "state": state,
        "resource_ids": resource_ids,
        "target_ids": [target_id],
        "mapped_plan_ids": [f"plan_{kcid[-3:]}"],
        "mapping_summary": {
            "plan_title": f"{title}作战方案",
            "match_score": round(0.85 + 0.1 * (hash(kcid) % 10) / 10, 2),
            "estimated_time_sec": 1200 + int(kcid[-3:]) * 60,
            "remarks": f"与方案plan_{kcid[-3:]}匹配",
        },
        "raw_entries": raw_entries,
        "assigned_entries": assigned_entries,
    }


# 生成 6 条新数据（覆盖 6 种不同状态）
killchains = [
    make_killchain(
        "kill_chain_002", "对敌雷达站侦察杀伤链",
        "针对区域C的敌方雷达站，执行侦察→定位→评估的杀伤链。",
        "INIT", "target_002", ["侦察", "定位", "评估"], assigned=False
    ),
    make_killchain(
        "kill_chain_003", "对敌指挥所打击杀伤链",
        "针对区域D的敌方指挥所，执行侦察→瞄准/引导→打击→评估的杀伤链。",
        "READY", "target_003", ["侦察", "瞄准/引导", "打击", "评估"], assigned=True
    ),
    make_killchain(
        "kill_chain_004", "对敌弹药库评估杀伤链",
        "针对区域E的敌方弹药库，执行侦察→跟踪→评估的杀伤链。",
        "WAITING", "target_004", ["侦察", "跟踪", "评估"], assigned=False
    ),
    make_killchain(
        "kill_chain_005", "对敌通信站干扰杀伤链",
        "针对区域F的敌方通信站，执行侦察→干扰→评估的杀伤链。",
        "INTERUPT", "target_005", ["侦察", "干扰", "评估"], assigned=True
    ),
    make_killchain(
        "kill_chain_006", "对敌机场打击杀伤链",
        "针对区域G的敌方机场，执行侦察→定位→打击→评估的杀伤链。",
        "DONE", "target_006", ["侦察", "定位", "打击", "评估"], assigned=True
    ),
    make_killchain(
        "kill_chain_007", "对敌港口封锁杀伤链",
        "针对区域H的敌方港口，执行侦察→封锁→评估的杀伤链。",
        "DELETED", "target_007", ["侦察", "封锁", "评估"], assigned=False
    ),
]

payload = {
    "resources": killchains,
    "return_data_type": "typed",
    "ignore_errors": True,
}

print("准备导入以下杀伤链：")
for kc in killchains:
    print(f"  {kc['kill_chain_id']}: {kc['title']} [{kc['state']}] 条目:{len(kc['raw_entries'])}")

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

# 验证导入结果
print("\n验证导入结果...")
verify = requests.post(
    f"{BASE_URL}/api/v1/task_pool/resources/query",
    json={"task_type": "KILL_CHAIN", "limit": 20},
    timeout=10,
)
if verify.status_code == 200:
    items = verify.json()
    print(f"当前 KILL_CHAIN 总数: {len(items)}")
    for item in items:
        print(f"  - {item.get('resource_id')}: {item.get('raw_payload',{}).get('title','')} [{item.get('raw_payload',{}).get('state','')}]")
else:
    print(f"查询失败: {verify.status_code}")
