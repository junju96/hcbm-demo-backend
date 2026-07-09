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
OPERATOR_DATA_SERVER_BASE_URL = "http://25.11.1.56:28801"  # 操控席数据服务端
RESOURCE_POOL_BASE_URL = "http://25.11.1.178:28800"  # 资源池重构版服务端口
TIMEOUT_SECONDS = (1, 2)  # (connect timeout, read timeout)；连接 1s、读取 2s，断连时快速失败
MOCK_MODE = False  # False 时数据服务器不可达返回 None/错误，不返回 fake data

# 数据服务器接受的资源 state 合法值（PLAN / KILL_CHAIN 等通用）
VALID_RESOURCE_STATES = {
    "INIT", "READY", "WAITING", "ACTIVE", "INTERUPT",
    "DONE", "DELETED", "REVIEW", "DRAFT",
}


def validate_resource_state(resource: Dict[str, Any]) -> tuple[bool, str]:
    """校验资源 state 字段合法性，返回 (is_valid, error_message)"""
    state = resource.get("state")
    if state is None:
        return True, ""  # state 可选
    if state not in VALID_RESOURCE_STATES:
        return False, (
            f"非法 state '{state}'，合法值: "
            f"{', '.join(sorted(VALID_RESOURCE_STATES))}"
        )
    return True, ""


# ========== 内部缓存（用于非 KILL_CHAIN/PLAN 类型的本地数据）
# 注意：KILL_CHAIN 和 PLAN 类型不再使用本地 mock，全部从数据服务端查询


# ========== 内部 HTTP 调用 ==========

def _http_get(path: str, params: Optional[Dict] = None, silent: bool = False) -> Optional[Dict[str, Any]]:
    if not HAS_REQUESTS:
        return None
    url = f"{DATA_SERVER_BASE_URL}{path}"
    try:
        if not silent:
            print(f"[DS-OUT] GET  {url} | params={params}")
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        if not silent:
            print(f"[DS-IN ] GET  {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if not silent:
            print(f"[DS-ERR] GET  {url} | error={e}")
        return None


def _http_post(path: str, json_body: Optional[Dict] = None, silent: bool = False, timeout: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
    if not HAS_REQUESTS:
        return None
    url = f"{DATA_SERVER_BASE_URL}{path}"
    body_summary = json.dumps(json_body, ensure_ascii=False)[:300] if json_body else ""
    try:
        if not silent:
            print(f"[DS-OUT] POST {url} | body={body_summary}")
        resp = requests.post(url, json=json_body, timeout=timeout or TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        if not silent:
            print(f"[DS-IN ] POST {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if not silent:
            print(f"[DS-ERR] POST {url} | error={e}")
        return None


def _http_patch(path: str, json_body: Optional[Dict] = None, silent: bool = False) -> Optional[Dict[str, Any]]:
    if not HAS_REQUESTS:
        return None
    url = f"{DATA_SERVER_BASE_URL}{path}"
    body_summary = json.dumps(json_body, ensure_ascii=False)[:300] if json_body else ""
    try:
        if not silent:
            print(f"[DS-OUT] PATCH {url} | body={body_summary}")
        resp = requests.patch(url, json=json_body, timeout=TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        if not silent:
            print(f"[DS-IN ] PATCH {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if not silent:
            print(f"[DS-ERR] PATCH {url} | error={e}")
        return None


def forward_resources_to_targets(
    target_ips: List[str],
    resource_ids: List[str],
    timeout_seconds: int = 30,
    silent: bool = False,
) -> Optional[Dict[str, Any]]:
    """调用协同席数据服务器的 /ingestion/forward 接口，将资源下发到指定目标席位。"""
    if not HAS_REQUESTS:
        return None
    url = f"{DATA_SERVER_BASE_URL}/api/v1/task_pool/ingestion/forward"
    body = {
        "target_ips": target_ips,
        "resource_ids": resource_ids,
        "timeout_seconds": timeout_seconds,
    }
    body_summary = json.dumps(body, ensure_ascii=False)[:300]
    try:
        if not silent:
            print(f"[DS-OUT] POST {url} | body={body_summary}")
        resp = requests.post(url, json=body, timeout=(1, timeout_seconds), proxies={"http": None, "https": None})
        if not silent:
            print(f"[DS-IN ] POST {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if not silent:
            print(f"[DS-ERR] POST {url} | error={e}")
        return None

def get_kill_chain(resource_id: str) -> Optional[Dict[str, Any]]:
    """查询单个杀伤链详情"""
    data = _http_get(f"/api/v1/task_pool/resources/{resource_id}")
    return data


def query_kill_chains(limit: int = 20) -> List[Dict[str, Any]]:
    """查询所有杀伤链列表"""
    data = _http_post(
        "/api/v1/task_pool/resources/query",
        {"task_type": "KILL_CHAIN", "limit": limit},
    )
    if data is not None and isinstance(data, list):
        return data
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

    result = _http_post(
        "/api/v1/task_pool/ingestion/import",
        {"resources": [payload], "return_data_type": "typed", "ignore_errors": True},
    )
    return result


def patch_kill_chain(resource_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """更新杀伤链：将特有字段打包到 payload 中传递"""
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

    data = _http_patch(f"/api/v1/task_pool/resources/{resource_id}", patch_body)
    return data


def delete_kill_chain(resource_id: str) -> bool:
    """删除杀伤链：调用生命周期接口"""
    result = _http_post(
        f"/api/v1/task_pool/resources/{resource_id}/lifecycle",
        {"state": "DELETED", "reason": "user_deleted"},
    )
    return result is not None


# ========== 前端适配：转换为前端熟悉的数据结构 ==========

def _get_biz_field(data: Dict[str, Any], field: str, default: Any = "") -> Any:
    """优先从顶层读取业务字段，fallback 到 raw_payload"""
    return data.get(field) or data.get("raw_payload", {}).get(field, default)


def to_frontend_killchain(data: Dict[str, Any]) -> Dict[str, Any]:
    """将数据服务器返回的 KillChain (TaskView) 转换为前端格式

    注意：优先从顶层字段读取业务数据，顶层不存在时 fallback 到 raw_payload。

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


# ========== 操控席数据服务端 HTTP 调用 ==========

def _http_get_operator(path: str, params: Optional[Dict] = None, silent: bool = False) -> Optional[Dict[str, Any]]:
    """向操控席数据服务器发送 GET 请求"""
    if not HAS_REQUESTS:
        return None
    url = f"{OPERATOR_DATA_SERVER_BASE_URL}{path}"
    try:
        if not silent:
            print(f"[OP-DS-OUT] GET  {url} | params={params}")
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        if not silent:
            print(f"[OP-DS-IN ] GET  {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if not silent:
            print(f"[OP-DS-ERR] GET  {url} | error={e}")
        return None


def _http_get_resource_pool(path: str, params: Optional[Dict] = None, silent: bool = False) -> Optional[Dict[str, Any]]:
    """向资源池服务（resource_pool_refactor）发送 GET 请求"""
    if not HAS_REQUESTS:
        return None
    url = f"{RESOURCE_POOL_BASE_URL}{path}"
    try:
        if not silent:
            print(f"[RP-OUT] GET  {url} | params={params}")
        resp = requests.get(url, params=params, timeout=TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        if not silent:
            print(f"[RP-IN ] GET  {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if not silent:
            print(f"[RP-ERR] GET  {url} | error={e}")
        return None


def _http_post_operator(path: str, json_body: Optional[Dict] = None, silent: bool = False, timeout: Optional[tuple] = None) -> Optional[Dict[str, Any]]:
    """向操控席数据服务器发送 POST 请求"""
    if not HAS_REQUESTS:
        return None
    url = f"{OPERATOR_DATA_SERVER_BASE_URL}{path}"
    body_summary = json.dumps(json_body, ensure_ascii=False)[:300] if json_body else ""
    try:
        if not silent:
            print(f"[OP-DS-OUT] POST {url} | body={body_summary}")
        resp = requests.post(url, json=json_body, timeout=timeout or TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        if not silent:
            print(f"[OP-DS-IN ] POST {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if not silent:
            print(f"[OP-DS-ERR] POST {url} | error={e}")
        return None


def _http_patch_operator(path: str, json_body: Optional[Dict] = None, silent: bool = False) -> Optional[Dict[str, Any]]:
    """向操控席数据服务器发送 PATCH 请求"""
    if not HAS_REQUESTS:
        return None
    url = f"{OPERATOR_DATA_SERVER_BASE_URL}{path}"
    body_summary = json.dumps(json_body, ensure_ascii=False)[:300] if json_body else ""
    try:
        if not silent:
            print(f"[OP-DS-OUT] PATCH {url} | body={body_summary}")
        resp = requests.patch(url, json=json_body, timeout=TIMEOUT_SECONDS, proxies={"http": None, "https": None})
        if not silent:
            print(f"[OP-DS-IN ] PATCH {url} | status={resp.status_code} | len={len(resp.text)}")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        if not silent:
            print(f"[OP-DS-ERR] PATCH {url} | error={e}")
        return None
