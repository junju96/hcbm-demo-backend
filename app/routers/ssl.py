"""
SSL 地图数据路由 — 接收 Mission Control 地图右键 SSL 菜单提交的数据
收到后直接透传给协同席数据服务端 /ingestion/import
"""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter
from typing import List, Dict, Any

from app.models.schemas import SSLMapDataRequest, ApiResponse
from app.services.data_server_client import _http_post

router = APIRouter()

# 内存存储：SSL 地图数据列表（备份）
_ssl_map_data_store: List[Dict[str, Any]] = []


@router.post("/ssl/map-data", response_model=ApiResponse)
async def receive_ssl_map_data(body: SSLMapDataRequest):
    """
    接收 SSL 地图右键菜单"确认"后发送的数据。
    直接透传给协同席数据服务端 /task_pool/ingestion/import 存入，
    同时保留一份本地内存备份供下游模块查询使用。
    """
    record_id = f"ssl:{uuid.uuid4().hex[:12]}"
    created_at = datetime.now(timezone.utc).isoformat()

    # 1. 组装数据服务端 resource 格式
    resource = {
        "task_type": "SSL_MAP_DATA",
        "resource_id": record_id,
        "resource_name": "SSL地图数据",
        "state": "READY",
        "method": body.method,
        "resource_list": body.resource_list,
        "object_list": [obj.model_dump() for obj in body.object_list],
        "created_at": created_at,
    }

    # 2. 透传给数据服务端
    import_result = None
    import_error = None
    try:
        import_result = _http_post(
            "/api/v1/task_pool/ingestion/import",
            {"resources": [resource], "return_data_type": "typed", "ignore_errors": True},
        )
    except Exception as e:
        import_error = str(e)

    # 3. 本地内存备份（无论远端是否成功）
    record = dict(resource)  # 复用 resource 结构
    _ssl_map_data_store.append(record)

    # 4. 按 method 维度整理，方便下游模块直接消费
    method_resources = {}
    for i, m in enumerate(body.method):
        method_resources[m] = body.resource_list[i] if i < len(body.resource_list) else []

    return ApiResponse(data={
        "record_id": record_id,
        "method_resources": method_resources,
        "object_count": len(body.object_list),
        "import_result": import_result,
        "import_error": import_error,
        "message": "SSL 地图数据已接收并已透传至数据服务端" if not import_error else "SSL 地图数据已接收，但透传失败",
    })


@router.get("/ssl/map-data", response_model=ApiResponse)
async def list_ssl_map_data(limit: int = 20):
    """获取 SSL 地图数据历史列表（按时间倒序）"""
    items = sorted(_ssl_map_data_store, key=lambda x: x["created_at"], reverse=True)[:limit]
    return ApiResponse(data={"items": items, "total": len(_ssl_map_data_store)})


@router.get("/ssl/map-data/latest", response_model=ApiResponse)
async def get_latest_ssl_map_data():
    """获取最新一条 SSL 地图数据（供其它模块调用传递数据）"""
    if not _ssl_map_data_store:
        return ApiResponse(code=404, message="暂无 SSL 地图数据", data=None)
    latest = max(_ssl_map_data_store, key=lambda x: x["created_at"])

    # 按 method 维度整理资源映射
    method_resources = {}
    for i, m in enumerate(latest["method"]):
        method_resources[m] = latest["resource_list"][i] if i < len(latest["resource_list"]) else []

    return ApiResponse(data={
        "record": latest,
        "method_resources": method_resources,
        "objects": latest["object_list"],
    })


@router.get("/ssl/map-data/{record_id}", response_model=ApiResponse)
async def get_ssl_map_data(record_id: str):
    """按 record_id 获取单条 SSL 地图数据"""
    record = next((r for r in _ssl_map_data_store if r["record_id"] == record_id), None)
    if not record:
        return ApiResponse(code=404, message=f"记录不存在: {record_id}", data=None)
    return ApiResponse(data=record)


@router.delete("/ssl/map-data/{record_id}", response_model=ApiResponse)
async def delete_ssl_map_data(record_id: str):
    """删除单条 SSL 地图数据"""
    global _ssl_map_data_store
    original_len = len(_ssl_map_data_store)
    _ssl_map_data_store = [r for r in _ssl_map_data_store if r["record_id"] != record_id]
    deleted = original_len - len(_ssl_map_data_store)
    return ApiResponse(data={"deleted": deleted, "record_id": record_id})


@router.post("/ssl/map-data/clear", response_model=ApiResponse)
async def clear_ssl_map_data():
    """清空所有 SSL 地图数据"""
    global _ssl_map_data_store
    count = len(_ssl_map_data_store)
    _ssl_map_data_store = []
    return ApiResponse(data={"cleared": count})
