from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

import requests

BASE_URL = "http://25.11.1.178:28801"
DEFAULT_LIMIT = 20
TIMEOUT_SECONDS = 5

class ImportRequest(BaseModel):
    resources: list[dict[str, Any]] = Field(default_factory=list)
    ignore_errors: bool = True


def fetch_aggregate_resources(limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:

    # 获取ssl
    # Response = 
    # {'resource_id': 'kill_chain:kill_chain_001', 'task_type': 'KILL_CHAIN', 'attributes': {'cache_key': 'kill_chain:kill_chain_001'}, 'search_text': "KILL_CHAIN kill_chain-kill_chain_001 针对区域B的敌方T-72坦克，执行侦察→识别→打击→评估的完整杀伤链。 {'cache_key': 'kill_chain:kill_chain_001'} ACTIVE", 'source': {'source_data_module': 'task_pool', 'source_topic': 'api/import', 'source_type': 'api', 'last_update_at': '2026-05-27T05:06:24.503814+00:00'}, 'raw_payload': {'task_type': 'KILL_CHAIN', 'title': '对敌装甲目标杀伤链', 'kill_chain_id': 'kill_chain_001', 'description': '针对区域B的敌方T-72坦克，执行侦察→识别→打击→评估的完整杀伤链。', 'state': 'ACTIVE', 'resource_ids': ['eq_无人车A', 'eq_巡逻无人机', 'eq_无人车B', 'target_001'], 'target_ids': ['target_001'], 'mapped_plan_ids': ['plan_001'], 'mapping_summary': {'plan_title': '地面引导与打击作战方案', 'match_score': 0.95, 'estimated_time_sec': 1800, 'remarks': '与方案plan_001高度匹配，满足时间窗口要求'}, 'raw_entries': [{'entry_id': 'entry_01', 'phase': 'RAW', 'entry_seq': 1, 'target_ids': ['target_001'], 'operation': '侦察', 'executor_options': [{'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': False, 'note': '配备光电传感器，适合近距离侦察'}, {'executor_id': 'eq_巡逻无人机', 'allocation_count': 1, 'locked': False, 'note': '可提供空中视角，但续航较短'}], 'selected_executor': None, 'locked': False, 'is_valid': True, 'notes': '需在目标进入开阔区域后执行'}, {'entry_id': 'entry_02', 'phase': 'RAW', 'entry_seq': 2, 'target_ids': ['target_001'], 'operation': '识别', 'executor_options': [{'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': False, 'note': '利用白光/热像进行目标确认'}, {'executor_id': 'eq_巡逻无人机', 'allocation_count': 1, 'locked': False, 'note': '通过图像识别算法验证'}], 'selected_executor': None, 'locked': False, 'is_valid': True, 'notes': '识别置信度需高于90%'}, {'entry_id': 'entry_03', 'phase': 'RAW', 'entry_seq': 3, 'target_ids': ['target_001'], 'operation': '打击', 'executor_options': [{'executor_id': 'eq_无人车B', 'allocation_count': 2, 'locked': False, 'note': '主炮备弹12发，建议使用2发确保毁伤'}], 'selected_executor': None, 'locked': False, 'is_valid': True, 'notes': '打击窗口宽度30秒'}, {'entry_id': 'entry_04', 'phase': 'RAW', 'entry_seq': 4, 'target_ids': ['target_001'], 'operation': '评估', 'executor_options': [{'executor_id': 'eq_巡逻无人机', 'allocation_count': 1, 'locked': False, 'note': '打击后飞越目标区域采集毁伤图像'}, {'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': False, 'note': '抵近观察热特征变化'}], 'selected_executor': None, 'locked': False, 'is_valid': True, 'notes': '需在打击后2分钟内完成评估'}], 'assigned_entries': [{'entry_id': 'entry_01', 'phase': 'ASSIGNED', 'entry_seq': 1, 'target_ids': ['target_001'], 'operation': '侦察', 'executor_options': [{'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': True, 'note': '最终选定'}], 'selected_executor': 'eq_无人车A', 'locked': True, 'is_valid': True, 'notes': '已分配，无人车A已就位'}, {'entry_id': 'entry_02', 'phase': 'ASSIGNED', 'entry_seq': 2, 'target_ids': ['target_001'], 'operation': '识别', 'executor_options': [{'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': True, 'note': '使用白光/热像识别'}], 'selected_executor': 'eq_无人车A', 'locked': True, 'is_valid': True, 'notes': '已分配'}, {'entry_id': 'entry_03', 'phase': 'ASSIGNED', 'entry_seq': 3, 'target_ids': ['target_001'], 'operation': '打击', 'executor_options': [{'executor_id': 'eq_无人车B', 'allocation_count': 2, 'locked': True, 'note': '使用高爆穿甲弹'}], 'selected_executor': 'eq_无人车B', 'locked': True, 'is_valid': True, 'notes': '待识别确认后立即执行'}, {'entry_id': 'entry_04', 'phase': 'ASSIGNED', 'entry_seq': 4, 'target_ids': ['target_001'], 'operation': '评估', 'executor_options': [{'executor_id': 'eq_巡逻无人机', 'allocation_count': 1, 'locked': True, 'note': '打击后飞越评估'}], 'selected_executor': 'eq_巡逻无人机', 'locked': True, 'is_valid': True, 'notes': '已分配'}]}, 'relations': [], 'created_at': '2026-05-27T03:25:31.058199Z', 'updated_at': '2026-05-27T05:29:29.201226Z', 'connections': [], 'dependencies': [], 'title': 'kill_chain-kill_chain_001', 'kill_chain_id': 'kill_chain_001', 'description': '针对区域B的敌方T-72坦克，执行侦察→识别→打击→评估的完整杀伤链。', 'raw_entries': [{'entry_id': 'entry_01', 'phase': 'RAW', 'entry_seq': 1, 'target_ids': ['target_003'], 'operation': '侦察', 'executor_options': [{'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': False, 'note': '配备光电传感器，适合近距离侦察'}, {'executor_id': 'eq_巡逻无人机', 'allocation_count': 1, 'locked': False, 'note': '可提供空中视角，但受天气影响较大'}], 'selected_executor': None, 'locked': False, 'is_valid': True, 'notes': '需在目标进入开阔区域后执行，注意电磁干扰'}, {'entry_id': 'entry_02', 'phase': 'RAW', 'entry_seq': 2, 'target_ids': ['target_003'], 'operation': '识别', 'executor_options': [{'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': False, 'note': '利用白光/热像进行目标确认'}, {'executor_id': 'eq_巡逻无人机', 'allocation_count': 1, 'locked': False, 'note': '通过图像识别算法验证'}, {'executor_id': 'eq_通信车C', 'allocation_count': 1, 'locked': False, 'note': '提供中继，确保数据回传'}], 'selected_executor': None, 'locked': False, 'is_valid': True, 'notes': '识别置信度需高于95%'}, {'entry_id': 'entry_03', 'phase': 'RAW', 'entry_seq': 3, 'target_ids': ['target_003'], 'operation': '打击', 'executor_options': [{'executor_id': 'eq_无人车B', 'allocation_count': 3, 'locked': False, 'note': '主炮备弹12发，建议使用3发确保毁伤'}], 'selected_executor': None, 'locked': False, 'is_valid': True, 'notes': '打击窗口宽度25秒'}, {'entry_id': 'entry_04', 'phase': 'RAW', 'entry_seq': 4, 'target_ids': ['target_003'], 'operation': '评估', 'executor_options': [{'executor_id': 'eq_巡逻无人机', 'allocation_count': 1, 'locked': False, 'note': '打击后飞越目标区域采集毁伤图像'}], 'selected_executor': None, 'locked': False, 'is_valid': True, 'notes': '需在打击后90秒内完成评估'}], 'assigned_entries': [{'entry_id': 'entry_01', 'phase': 'ASSIGNED', 'entry_seq': 1, 'target_ids': ['target_001'], 'operation': '侦察', 'executor_options': [{'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': True, 'note': '最终选定'}], 'selected_executor': 'eq_无人车A', 'locked': True, 'is_valid': True, 'notes': '已分配，无人车A已就位'}, {'entry_id': 'entry_02', 'phase': 'ASSIGNED', 'entry_seq': 2, 'target_ids': ['target_001'], 'operation': '识别', 'executor_options': [{'executor_id': 'eq_无人车A', 'allocation_count': 1, 'locked': True, 'note': '使用白光/热像识别'}], 'selected_executor': 'eq_无人车A', 'locked': True, 'is_valid': True, 'notes': '已分配'}, {'entry_id': 'entry_03', 'phase': 'ASSIGNED', 'entry_seq': 3, 'target_ids': ['target_001'], 'operation': '打击', 'executor_options': [{'executor_id': 'eq_无人车B', 'allocation_count': 2, 'locked': True, 'note': '使用高爆穿甲弹'}], 'selected_executor': 'eq_无人车B', 'locked': True, 'is_valid': True, 'notes': '待识别确认后立即执行'}, {'entry_id': 'entry_04', 'phase': 'ASSIGNED', 'entry_seq': 4, 'target_ids': ['target_001'], 'operation': '评估', 'executor_options': [{'executor_id': 'eq_巡逻无人机', 'allocation_count': 1, 'locked': True, 'note': '打击后飞越评估'}], 'selected_executor': 'eq_巡逻无人机', 'locked': True, 'is_valid': True, 'notes': '已分配'}], 'resource_ids': ['eq_无人车A', 'eq_巡逻无人机', 'eq_无人车B', 'target_001'], 'target_ids': ['target_002', 'target_003'], 'mapped_plan_ids': ['plan_003', 'plan_004'], 'mapping_summary': {'plan_title': '地面引导与打击作战方案（加强版）', 'match_score': 0.88, 'estimated_time_sec': 2100, 'remarks': '匹配度良好，但需注意通信覆盖距离'}, 'state': 'ACTIVE'}

    response = requests.get(
        f"{BASE_URL}/api/v1/task_pool/resources/kill_chain:kill_chain_001",
        params={"limit": limit, "include_deleted": False, "send_notification": False},
        timeout=TIMEOUT_SECONDS,
    )


    # 插入ssl
    # payload = {
    #     "resources": [
    #         {
    #             "task_type": "KILL_CHAIN",
    #             "title": "对敌装甲目标杀伤链",
    #             "kill_chain_id": "kill_chain_001",
    #             "description": "针对区域B的敌方T-72坦克，执行侦察→识别→打击→评估的完整杀伤链。",
    #             "state": "ACTIVE",
    #             "resource_ids": [
    #                 "eq_无人车A",
    #                 "eq_巡逻无人机",
    #                 "eq_无人车B",
    #                 "target_001"
    #             ],
    #             "target_ids": [
    #                 "target_001"
    #             ],
    #             "mapped_plan_ids": [
    #                 "plan_001"
    #             ],
    #             "mapping_summary": {
    #                 "plan_title": "地面引导与打击作战方案",
    #                 "match_score": 0.95,
    #                 "estimated_time_sec": 1800,
    #                 "remarks": "与方案plan_001高度匹配，满足时间窗口要求"
    #             },
    #             "raw_entries": [
    #                 {
    #                 "entry_id": "entry_01",
    #                 "phase": "RAW",
    #                 "entry_seq": 1,
    #                 "target_ids": ["target_001"],
    #                 "operation": "侦察",
    #                 "executor_options": [
    #                     {
    #                     "executor_id": "eq_无人车A",
    #                     "allocation_count": 1,
    #                     "locked": False,
    #                     "note": "配备光电传感器，适合近距离侦察"
    #                     },
    #                     {
    #                     "executor_id": "eq_巡逻无人机",
    #                     "allocation_count": 1,
    #                     "locked": False,
    #                     "note": "可提供空中视角，但续航较短"
    #                     }
    #                 ],
    #                 "selected_executor": None,
    #                 "locked": False,
    #                 "is_valid": True,
    #                 "notes": "需在目标进入开阔区域后执行"
    #                 },
    #                 {
    #                 "entry_id": "entry_02",
    #                 "phase": "RAW",
    #                 "entry_seq": 2,
    #                 "target_ids": ["target_001"],
    #                 "operation": "识别",
    #                 "executor_options": [
    #                     {
    #                     "executor_id": "eq_无人车A",
    #                     "allocation_count": 1,
    #                     "locked": False,
    #                     "note": "利用白光/热像进行目标确认"
    #                     },
    #                     {
    #                     "executor_id": "eq_巡逻无人机",
    #                     "allocation_count": 1,
    #                     "locked": False,
    #                     "note": "通过图像识别算法验证"
    #                     }
    #                 ],
    #                 "selected_executor": None,
    #                 "locked": False,
    #                 "is_valid": True,
    #                 "notes": "识别置信度需高于90%"
    #                 },
    #                 {
    #                 "entry_id": "entry_03",
    #                 "phase": "RAW",
    #                 "entry_seq": 3,
    #                 "target_ids": ["target_001"],
    #                 "operation": "打击",
    #                 "executor_options": [
    #                     {
    #                     "executor_id": "eq_无人车B",
    #                     "allocation_count": 2,
    #                     "locked": False,
    #                     "note": "主炮备弹12发，建议使用2发确保毁伤"
    #                     }
    #                 ],
    #                 "selected_executor": None,
    #                 "locked": False,
    #                 "is_valid": True,
    #                 "notes": "打击窗口宽度30秒"
    #                 },
    #                 {
    #                 "entry_id": "entry_04",
    #                 "phase": "RAW",
    #                 "entry_seq": 4,
    #                 "target_ids": ["target_001"],
    #                 "operation": "评估",
    #                 "executor_options": [
    #                     {
    #                     "executor_id": "eq_巡逻无人机",
    #                     "allocation_count": 1,
    #                     "locked": False,
    #                     "note": "打击后飞越目标区域采集毁伤图像"
    #                     },
    #                     {
    #                     "executor_id": "eq_无人车A",
    #                     "allocation_count": 1,
    #                     "locked": False,
    #                     "note": "抵近观察热特征变化"
    #                     }
    #                 ],
    #                 "selected_executor": None,
    #                 "locked": False,
    #                 "is_valid": True,
    #                 "notes": "需在打击后2分钟内完成评估"
    #                 }
    #             ],
    #             "assigned_entries": [
    #                 {
    #                 "entry_id": "entry_01",
    #                 "phase": "ASSIGNED",
    #                 "entry_seq": 1,
    #                 "target_ids": ["target_001"],
    #                 "operation": "侦察",
    #                 "executor_options": [
    #                     {
    #                     "executor_id": "eq_无人车A",
    #                     "allocation_count": 1,
    #                     "locked": True,
    #                     "note": "最终选定"
    #                     }
    #                 ],
    #                 "selected_executor": "eq_无人车A",
    #                 "locked": True,
    #                 "is_valid": True,
    #                 "notes": "已分配，无人车A已就位"
    #                 },
    #                 {
    #                 "entry_id": "entry_02",
    #                 "phase": "ASSIGNED",
    #                 "entry_seq": 2,
    #                 "target_ids": ["target_001"],
    #                 "operation": "识别",
    #                 "executor_options": [
    #                     {
    #                     "executor_id": "eq_无人车A",
    #                     "allocation_count": 1,
    #                     "locked": True,
    #                     "note": "使用白光/热像识别"
    #                     }
    #                 ],
    #                 "selected_executor": "eq_无人车A",
    #                 "locked": True,
    #                 "is_valid": True,
    #                 "notes": "已分配"
    #                 },
    #                 {
    #                 "entry_id": "entry_03",
    #                 "phase": "ASSIGNED",
    #                 "entry_seq": 3,
    #                 "target_ids": ["target_001"],
    #                 "operation": "打击",
    #                 "executor_options": [
    #                     {
    #                     "executor_id": "eq_无人车B",
    #                     "allocation_count": 2,
    #                     "locked": True,
    #                     "note": "使用高爆穿甲弹"
    #                     }
    #                 ],
    #                 "selected_executor": "eq_无人车B",
    #                 "locked": True,
    #                 "is_valid": True,
    #                 "notes": "待识别确认后立即执行"
    #                 },
    #                 {
    #                 "entry_id": "entry_04",
    #                 "phase": "ASSIGNED",
    #                 "entry_seq": 4,
    #                 "target_ids": ["target_001"],
    #                 "operation": "评估",
    #                 "executor_options": [
    #                     {
    #                     "executor_id": "eq_巡逻无人机",
    #                     "allocation_count": 1,
    #                     "locked": True,
    #                     "note": "打击后飞越评估"
    #                     }
    #                 ],
    #                 "selected_executor": "eq_巡逻无人机",
    #                 "locked": True,
    #                 "is_valid": True,
    #                 "notes": "已分配"
    #                 }
    #             ]
    #             }
    #     ],
    #     "return_data_type":"full",
    #     "ignore_errors": True
    # }

    # response = requests.post(
    #     f"{BASE_URL}/api/v1/task_pool/ingestion/import",
    #     json=payload,
    #     timeout=TIMEOUT_SECONDS,
    # )



    # 更新
    # patch_payload = {"payload": {
    #     "target_ids": ["target_002", "target_003"],
    #     "mapped_plan_ids": ["plan_003", "plan_004"],
    #     "mapping_summary": {
    #         "plan_title": "地面引导与打击作战方案（加强版）",
    #         "match_score": 0.88,
    #         "estimated_time_sec": 2100,
    #         "remarks": "匹配度良好，但需注意通信覆盖距离"
    #     },
    #     }}

    # response = requests.patch(
    #     f"{BASE_URL}/api/v1/task_pool/resources/kill_chain:kill_chain_001",
    #     json=patch_payload,
    #     timeout=TIMEOUT_SECONDS,
    # )

    response.raise_for_status()
    payload = response.json()
    return payload


def search_aggregate_resources(query: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    response = requests.post(
        f"{BASE_URL}/api/v1/resources/search",
        json={"query": query, "limit": limit},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected response type: {type(payload)!r}")
    return payload


def build_algorithm_input(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for resource in resources:
        attributes = resource.get("attributes") or {}
        state = resource.get("state") or {}
        child_collections = []
        for key, value in attributes.items():
            if isinstance(value, list) and value:
                child_collections.append({"name": key, "count": len(value)})
        items.append(
            {
                "resource_id": resource.get("resource_id"),
                "resource_name": resource.get("resource_name"),
                "resource_type": resource.get("resource_type"),
                "entity_kind": resource.get("entity_kind"),
                "online_status": state.get("online_status"),
                "mission_status": state.get("mission_status"),
                "children_summary": child_collections,
            }
        )
    return items


def main() -> int:
    try:
        resources = fetch_aggregate_resources()
    except requests.RequestException as exc:
        print(f"[ERROR] 无法访问资源池服务：{exc}")
        print(f"[HINT] 请确认服务已启动：{BASE_URL}")
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"[ERROR] 读取聚合资源失败：{exc}")
        return 1

    if not resources:
        print("[INFO] 当前没有可用的聚合资源。")
        return 0

    print(resources)
    # print(type(next(iter(resources.get("location")[0].values()))))
    # algorithm_input = build_algorithm_input(resources)
    # print(f"[INFO] 原始聚合资源数量: {len(resources)}")
    # print("[INFO] 提供给算法的聚合输入示例:")
    # print(json.dumps(algorithm_input[:3], ensure_ascii=False, indent=2))

    # if len(resources) >= 1:
    #     keyword = str(resources[0].get("resource_name") or "").strip()
    #     if keyword:
    #         try:
    #             matched = search_aggregate_resources(keyword, limit=5)
    #             print(f"[INFO] 使用关键词 `{keyword}` 搜索到的聚合资源数量: {len(matched)}")
    #         except requests.RequestException as exc:
    #             print(f"[WARN] 聚合搜索接口调用失败：{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
