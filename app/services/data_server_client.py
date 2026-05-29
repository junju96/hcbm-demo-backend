"""
数据服务器 (task_pool) HTTP 客户端
支持真实调用 + test.py 数据 fallback（mock 模式）
"""

import json
import copy
import uuid
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ========== 配置 ==========

DATA_SERVER_BASE_URL = "http://25.11.1.178:28801"
TIMEOUT_SECONDS = 5
MOCK_MODE = True  # True 时数据服务器不可达也返回 fake data


# ========== Fake Response 数据（来自 test.py） ==========

_FAKE_KILLCHAIN = {
    "resource_id": "kill_chain:kill_chain_001",
    "task_type": "KILL_CHAIN",
    "attributes": {"cache_key": "kill_chain:kill_chain_001"},
    "search_text": "KILL_CHAIN kill_chain-kill_chain_001 针对区域B的敌方T-72坦克，执行侦察→识别→打击→评估的完整杀伤链。 ACTIVE",
    "source": {
        "source_data_module": "task_pool",
        "source_topic": "api/import",
        "source_type": "api",
        "last_update_at": "2026-05-27T05:06:24.503814+00:00",
    },
    "raw_payload": {},
    "title": "对敌装甲目标杀伤链",
    "kill_chain_id": "kill_chain_001",
    "description": "针对区域B的敌方T-72坦克，执行侦察→识别→打击→评估的完整杀伤链。",
    "state": "ACTIVE",
    "resource_ids": ["eq_无人车A", "eq_巡逻无人机", "eq_无人车B", "target_001"],
    "target_ids": ["target_001"],
    "mapped_plan_ids": ["plan_001"],
    "mapping_summary": {
        "plan_title": "地面引导与打击作战方案",
        "match_score": 0.95,
        "estimated_time_sec": 1800,
        "remarks": "与方案plan_001高度匹配，满足时间窗口要求",
    },
    "raw_entries": [
        {
            "entry_id": "entry_01",
            "phase": "RAW",
            "entry_seq": 1,
            "target_ids": ["target_001"],
            "operation": "侦察",
            "executor_options": [
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": False, "note": "配备光电传感器，适合近距离侦察"},
                {"executor_id": "eq_巡逻无人机", "allocation_count": 1, "locked": False, "note": "可提供空中视角，但续航较短"},
            ],
            "selected_executor": None,
            "locked": False,
            "is_valid": True,
            "notes": "需在目标进入开阔区域后执行",
        },
        {
            "entry_id": "entry_02",
            "phase": "RAW",
            "entry_seq": 2,
            "target_ids": ["target_001"],
            "operation": "识别",
            "executor_options": [
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": False, "note": "利用白光/热像进行目标确认"},
                {"executor_id": "eq_巡逻无人机", "allocation_count": 1, "locked": False, "note": "通过图像识别算法验证"},
            ],
            "selected_executor": None,
            "locked": False,
            "is_valid": True,
            "notes": "识别置信度需高于90%",
        },
        {
            "entry_id": "entry_03",
            "phase": "RAW",
            "entry_seq": 3,
            "target_ids": ["target_001"],
            "operation": "打击",
            "executor_options": [
                {"executor_id": "eq_无人车B", "allocation_count": 2, "locked": False, "note": "主炮备弹12发，建议使用2发确保毁伤"},
            ],
            "selected_executor": None,
            "locked": False,
            "is_valid": True,
            "notes": "打击窗口宽度30秒",
        },
        {
            "entry_id": "entry_04",
            "phase": "RAW",
            "entry_seq": 4,
            "target_ids": ["target_001"],
            "operation": "评估",
            "executor_options": [
                {"executor_id": "eq_巡逻无人机", "allocation_count": 1, "locked": False, "note": "打击后飞越目标区域采集毁伤图像"},
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": False, "note": "抵近观察热特征变化"},
            ],
            "selected_executor": None,
            "locked": False,
            "is_valid": True,
            "notes": "需在打击后2分钟内完成评估",
        },
    ],
    "assigned_entries": [
        {
            "entry_id": "entry_01",
            "phase": "ASSIGNED",
            "entry_seq": 1,
            "target_ids": ["target_001"],
            "operation": "侦察",
            "executor_options": [
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": True, "note": "最终选定"},
            ],
            "selected_executor": "eq_无人车A",
            "locked": True,
            "is_valid": True,
            "notes": "已分配，无人车A已就位",
        },
        {
            "entry_id": "entry_02",
            "phase": "ASSIGNED",
            "entry_seq": 2,
            "target_ids": ["target_001"],
            "operation": "识别",
            "executor_options": [
                {"executor_id": "eq_无人车A", "allocation_count": 1, "locked": True, "note": "使用白光/热像识别"},
            ],
            "selected_executor": "eq_无人车A",
            "locked": True,
            "is_valid": True,
            "notes": "已分配",
        },
        {
            "entry_id": "entry_03",
            "phase": "ASSIGNED",
            "entry_seq": 3,
            "target_ids": ["target_001"],
            "operation": "打击",
            "executor_options": [
                {"executor_id": "eq_无人车B", "allocation_count": 2, "locked": True, "note": "使用高爆穿甲弹"},
            ],
            "selected_executor": "eq_无人车B",
            "locked": True,
            "is_valid": True,
            "notes": "待识别确认后立即执行",
        },
        {
            "entry_id": "entry_04",
            "phase": "ASSIGNED",
            "entry_seq": 4,
            "target_ids": ["target_001"],
            "operation": "评估",
            "executor_options": [
                {"executor_id": "eq_巡逻无人机", "allocation_count": 1, "locked": True, "note": "打击后飞越评估"},
            ],
            "selected_executor": "eq_巡逻无人机",
            "locked": True,
            "is_valid": True,
            "notes": "已分配",
        },
    ],
}

_FAKE_KILLCHAIN_LIST = [
    {
        "resource_id": "kill_chain:kill_chain_001",
        "task_type": "KILL_CHAIN",
        "kill_chain_id": "kill_chain_001",
        "title": "对敌装甲目标杀伤链",
        "description": "针对区域B的敌方T-72坦克，执行侦察→识别→打击→评估的完整杀伤链。",
        "state": "ACTIVE",
        "target_count": 1,
        "entry_count": 4,
    },
]

# 内存缓存（模拟数据服务器状态）
_killchain_store: Dict[str, Dict[str, Any]] = {
    "kill_chain:kill_chain_001": copy.deepcopy(_FAKE_KILLCHAIN),
}


# ========== 内部 HTTP 调用 ==========

def _http_get(path: str, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    if not HAS_REQUESTS:
        return None
    url = f"{DATA_SERVER_BASE_URL}{path}"
    try:
        print(f"[DS-OUT] GET  {url} | params={params}")
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        print(f"[DS-IN ] GET  {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[DS-ERR] GET  {url} | error={e}")
        return None


def _http_post(path: str, json_body: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    if not HAS_REQUESTS:
        return None
    url = f"{DATA_SERVER_BASE_URL}{path}"
    body_summary = json.dumps(json_body, ensure_ascii=False)[:300] if json_body else ""
    try:
        print(f"[DS-OUT] POST {url} | body={body_summary}")
        resp = requests.post(url, json=json_body, timeout=TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        print(f"[DS-IN ] POST {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[DS-ERR] POST {url} | error={e}")
        return None


def _http_patch(path: str, json_body: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    if not HAS_REQUESTS:
        return None
    url = f"{DATA_SERVER_BASE_URL}{path}"
    body_summary = json.dumps(json_body, ensure_ascii=False)[:300] if json_body else ""
    try:
        print(f"[DS-OUT] PATCH {url} | body={body_summary}")
        resp = requests.patch(url, json=json_body, timeout=TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        print(f"[DS-IN ] PATCH {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[DS-ERR] PATCH {url} | error={e}")
        return None


# ========== 对外接口 ==========

def get_kill_chain(resource_id: str) -> Optional[Dict[str, Any]]:
    """查询单个杀伤链详情"""
    # 1. 尝试真实调用数据服务器
    data = _http_get(f"/api/v1/task_pool/resources/{resource_id}")
    if data is not None:
        return data

    # 2. MOCK fallback
    if MOCK_MODE:
        return copy.deepcopy(_killchain_store.get(resource_id))
    return None


def query_kill_chains(limit: int = 20) -> List[Dict[str, Any]]:
    """查询所有杀伤链列表"""
    # 1. 尝试真实调用
    data = _http_post(
        "/api/v1/task_pool/resources/query",
        {"task_type": "KILL_CHAIN", "limit": limit},
    )
    if data is not None and isinstance(data, list):
        return data

    # 2. MOCK fallback
    if MOCK_MODE:
        return [copy.deepcopy(_FAKE_KILLCHAIN)]
    return []


def create_kill_chain(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """创建杀伤链：调用数据服务器 import 接口"""
    resource_id = f"kill_chain:{payload.get('kill_chain_id', uuid.uuid4().hex[:8])}"
    payload["resource_id"] = resource_id
    payload["task_type"] = "KILL_CHAIN"
    if "created_at" not in payload:
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
    if "updated_at" not in payload:
        payload["updated_at"] = payload["created_at"]

    # 1. 尝试真实调用
    result = _http_post(
        "/api/v1/task_pool/ingestion/import",
        {"resources": [payload], "return_data_type": "typed", "ignore_errors": True},
    )
    if result is not None:
        return result

    # 2. MOCK fallback：写入内存缓存
    if MOCK_MODE:
        _killchain_store[resource_id] = copy.deepcopy(payload)
        return {
            "requested_resources": 1,
            "normalized_resources": 1,
            "upserted_resources": 1,
            "failures": [],
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "summary": {"resource_id": resource_id},
        }
    return None


def patch_kill_chain(resource_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新杀伤链：将特有字段打包到 payload 中传递"""
    # 分离通用字段和杀伤链特有字段
    generic_fields = {}
    killchain_fields = {}

    generic_keys = {"title", "description", "state", "search_text"}
    for k, v in payload.items():
        if k in generic_keys:
            generic_fields[k] = v
        else:
            killchain_fields[k] = v

    patch_body = copy.deepcopy(generic_fields)
    if killchain_fields:
        patch_body["payload"] = killchain_fields

    # 1. 尝试真实调用
    data = _http_patch(f"/api/v1/task_pool/resources/{resource_id}", patch_body)
    if data is not None:
        return data

    # 2. MOCK fallback：更新内存缓存
    if MOCK_MODE and resource_id in _killchain_store:
        resource = _killchain_store[resource_id]
        for k, v in generic_fields.items():
            if v is not None:
                resource[k] = v
        if "payload" in patch_body:
            for k, v in patch_body["payload"].items():
                if v is not None:
                    resource[k] = v
        resource["updated_at"] = datetime.now(timezone.utc).isoformat()
        return copy.deepcopy(resource)
    return None


def delete_kill_chain(resource_id: str) -> bool:
    """删除杀伤链：调用生命周期接口或直接从缓存移除"""
    # 1. 尝试真实调用生命周期接口
    result = _http_post(
        f"/api/v1/task_pool/resources/{resource_id}/lifecycle",
        {"state": "DELETED", "reason": "user_deleted"},
    )
    if result is not None:
        return True

    # 2. MOCK fallback
    if MOCK_MODE and resource_id in _killchain_store:
        del _killchain_store[resource_id]
        return True
    return False


# ========== 前端适配：转换为前端熟悉的数据结构 ==========

def _get_biz_field(data: Dict[str, Any], field: str, default: Any = "") -> Any:
    """优先从 raw_payload 读取业务字段，fallback 到顶层字段"""
    return data.get("raw_payload", {}).get(field, data.get(field, default))


def to_frontend_killchain(data: Dict[str, Any]) -> Dict[str, Any]:
    """将数据服务器返回的 KillChain (TaskView) 转换为前端格式

    注意：数据服务器把业务字段存放在 raw_payload 中，顶层 title 等字段
    通常是系统生成的标识（如 kill_chain-kill_chain_001），因此优先取
    raw_payload 内的值。

    KillChain state 合法枚举值：
        INIT, READY, WAITING, ACTIVE, INTERUPT, DONE, DELETED
    """
    if not data:
        return {}

    # 提取 targets 名称列表（用于前端显示）
    target_names = []
    for tid in _get_biz_field(data, "target_ids", []):
        # 简化：从 target_id 提取名称
        target_names.append(tid.replace("target_", "目标").replace("target-", "目标"))

    # entries 兼容：数据服务器分 raw_entries / assigned_entries
    # 前端当前使用 entries（混合），这里保留原始结构
    return {
        "resource_id": data.get("resource_id", ""),
        "kill_chain_id": _get_biz_field(data, "kill_chain_id", ""),
        "title": _get_biz_field(data, "title", ""),
        "description": _get_biz_field(data, "description", ""),
        "state": _get_biz_field(data, "state", "INIT"),
        "target_ids": _get_biz_field(data, "target_ids", []),
        "target_names": target_names,
        "resource_ids": _get_biz_field(data, "resource_ids", []),
        "mapped_plan_ids": _get_biz_field(data, "mapped_plan_ids", []),
        "mapping_summary": _get_biz_field(data, "mapping_summary", {}),
        "raw_entries": _get_biz_field(data, "raw_entries", []),
        "assigned_entries": _get_biz_field(data, "assigned_entries", []),
        "network": _get_biz_field(data, "network", {"nodes": [], "edges": []}),
        "is_mock": _get_biz_field(data, "is_mock", False),
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
    }


def to_frontend_killchain_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """列表摘要转换"""
    results = []
    for item in items:
        target_count = len(_get_biz_field(item, "target_ids", []))
        raw_count = len(_get_biz_field(item, "raw_entries", []))
        assigned_count = len(_get_biz_field(item, "assigned_entries", []))
        results.append({
            "kill_chain_id": _get_biz_field(item, "kill_chain_id", ""),
            "resource_id": item.get("resource_id", ""),
            "task_type": item.get("task_type", "KILL_CHAIN"),
            "title": _get_biz_field(item, "title", ""),
            "description": _get_biz_field(item, "description", ""),
            "state": _get_biz_field(item, "state", "INIT"),
            "target_count": target_count,
            "entry_count": raw_count + assigned_count,
            "is_mock": _get_biz_field(item, "is_mock", False),
        })
    return results
