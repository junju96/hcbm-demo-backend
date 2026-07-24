"""
行动序列路由 — Action Sequence API

与杀伤链的区分：
  - kill_chain.py 处理 KILL_CHAIN 类型资源的 CRUD 和分配
  - action_sequence.py 处理 PLAN 类型方案的行动序列展示和控制

接口清单：
  GET  /api/v1/action-sequences/plans              查询方案列表
  GET  /api/v1/action-sequences/plans/{plan_id}    查询方案详情（含行动序列）
  POST /api/v1/action-sequences/plans/{plan_id}/start   开始执行
  POST /api/v1/action-sequences/plans/{plan_id}/pause   暂停执行
  POST /api/v1/action-sequences/plans/{plan_id}/resume  继续执行
  POST /api/v1/action-sequences/plans/{plan_id}/stop    停止/重置
"""

from typing import Any, Dict, List
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from pydantic import BaseModel
from typing import Any, Dict, Optional

from app.models.schemas import ApiResponse
from app.services.action_sequence_client import (
    query_plans,
    get_plan_detail,
    update_action_param,
    update_operator_action_param,
    get_first_vid,
    action_runtime,
    build_mission_payload,
    publish_control_mission,
    query_plans_operator,
    get_plan_detail_operator,
    import_plan_to_operator,
    create_operator_plan,
    update_operator_plan_locally,
    update_plan,
    sync_plan_to_operator,
    query_online_vehicles,
    query_online_vehicles_operator,
    delete_vehicle_operator,
    delete_vehicle,
    dispatch_plan_forward,
    PLAN_SSE_SCOPE,
    _http_get_operator,
    _http_post_operator,
    _http_patch_operator,
    _normalize_plan_field_names,
    _scale_coords_to_int,
)
from datetime import datetime, timezone
from app.services import zenoh_client
from app.services.task_pool import task_pool
from app.services import vehicle_control_client
from app.services import task_monitoring_client
from app.services.sse_manager import sse_manager

router = APIRouter()


class DispatchRequest(BaseModel):
    vehicle_vmfs: Optional[Dict[str, int]] = None
    vehicle_ips: Optional[Dict[str, str]] = None
    tid: Optional[int] = None
    vehicle_topic: Optional[str] = "ZD04"
    vehicle_vid: Optional[str] = None


class DispatchForwardRequest(BaseModel):
    target_ips: List[str]
    timeout_seconds: Optional[int] = 30


class ActionParamUpdateRequest(BaseModel):
    param: Dict[str, Any]


class SelectVehicleRequest(BaseModel):
    vehicle_id: str


@router.get("/action-sequences/connected-vehicles", response_model=ApiResponse)
async def list_connected_vehicles():
    """获取当前已连接车辆列表（从数据服务器资源池查询，用于操控席选择车辆）"""
    items = query_online_vehicles()
    selected = vehicle_control_client.get_selected_vehicle_id()
    return ApiResponse(data={
        "items": items,
        "selected": selected,
        "total": len(items),
    })


def _find_online_vehicle_by_id(vehicle_id: str, online_vehicles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """在数据服务器返回的在线车辆列表中按 vid 查找（兼容 equipment: 前缀）。"""
    target = (vehicle_id or "").replace("equipment:", "")
    for v in online_vehicles:
        vid = str(v.get("vid", "")).replace("equipment:", "")
        if vid and vid == target:
            return v
    return None


@router.get("/action-sequences/selected-vehicle", response_model=ApiResponse)
async def get_selected_vehicle():
    """获取当前已选中的车辆（从数据服务器资源池查询车辆信息）"""
    selected = vehicle_control_client.get_selected_vehicle_id()
    info = _find_online_vehicle_by_id(selected, query_online_vehicles()) if selected else None
    return ApiResponse(data={
        "selected": selected,
        "info": info,
    })


@router.post("/action-sequences/select-vehicle", response_model=ApiResponse)
async def select_vehicle(body: SelectVehicleRequest):
    """选中一辆车：从数据服务器确认在线后订阅 zenoh 反馈、记录选中状态"""
    vehicle_id = body.vehicle_id
    clean_vid = vehicle_id.replace("equipment:", "")
    info = _find_online_vehicle_by_id(vehicle_id, query_online_vehicles())
    if not info:
        return ApiResponse(code=404, message=f"车辆 {vehicle_id} 不在线或未找到", data=None)

    ok = zenoh_client.subscribe_vehicle_feedbacks(clean_vid)
    if ok:
        vehicle_control_client.set_selected_vehicle_id(vehicle_id)
        print(f"[AS-API] selected vehicle: {vehicle_id}, subscribed feedbacks")
        return ApiResponse(data={
            "selected": vehicle_id,
            "info": info,
            "subscribed": True,
        })
    return ApiResponse(code=500, message=f"订阅车辆 {vehicle_id} 反馈失败", data={"selected": vehicle_id})


@router.get("/action-sequences/plans", response_model=ApiResponse)
async def list_plans(limit: int = 200):
    """获取行动方案列表"""
    items = query_plans(limit=limit)
    print(f"[AS-API] list_plans returned {len(items)} items, first ids={[p.get('plan_id') for p in items[:3]]}")
    return ApiResponse(data={"items": items, "total": len(items)})


@router.get("/resources/by_type/{task_type}", response_model=ApiResponse)
async def list_resources_by_type(task_type: str, limit: int = 50):
    """按类型查询资源池资源（ROUTE / AREA / TARGET / EQUIPMENT 等）"""
    items = task_pool.query(task_type=task_type.upper(), limit=limit)
    return ApiResponse(data={"items": items, "total": len(items)})


@router.get("/action-sequences/vehicles", response_model=ApiResponse)
async def list_online_vehicles():
    """协同席 — 从资源池获取当前已连接的无人车列表"""
    items = query_online_vehicles()
    return ApiResponse(data={"items": items, "total": len(items)})


@router.get("/action-sequences/plans/{plan_id}", response_model=ApiResponse)
async def get_plan(plan_id: str):
    """获取方案详情（含阶段、编组、行动序列）"""
    detail = get_plan_detail(plan_id)
    if not detail:
        return ApiResponse(code=404, message="Plan not found", data=None)

    # 合并运行时状态
    runtime = action_runtime.get_state(detail.get("plan_id", plan_id))
    detail["runtime_state"] = runtime

    return ApiResponse(data=detail)


@router.patch("/action-sequences/plans/{plan_id}/actions/{action_id}", response_model=ApiResponse)
async def patch_action_param(plan_id: str, action_id: str, body: ActionParamUpdateRequest):
    """更新指定 action 的 param（支持本地 fake 数据调试）"""
    ok = update_action_param(plan_id, action_id, body.param)
    if not ok:
        return ApiResponse(code=404, message="Action not found or update failed", data=None)
    return ApiResponse(data={
        "plan_id": plan_id,
        "action_id": action_id,
        "updated": True,
    })


@router.patch("/action-sequences/operator/plans/{plan_id}/actions/{action_id}", response_model=ApiResponse)
async def patch_operator_action_param(plan_id: str, action_id: str, body: ActionParamUpdateRequest):
    """操控端 — 更新指定 action 的 param（仅更新本地 task_pool，不同步到数据服务器）"""
    ok = update_operator_action_param(plan_id, action_id, body.param)
    if not ok:
        return ApiResponse(code=404, message="Action not found or update failed", data=None)
    return ApiResponse(data={
        "plan_id": plan_id,
        "action_id": action_id,
        "updated": True,
    })


@router.post("/action-sequences/plans/{plan_id}/start", response_model=ApiResponse)
async def start_plan(plan_id: str):
    """开始执行行动序列 — 状态转移 + Zenoh control_mission (task_control=1)"""
    ok, msg = action_runtime.transit(plan_id, "ACTIVE")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)

    zenoh_ok, zenoh_msg = publish_control_mission(plan_id, task_control=1)
    return ApiResponse(data={
        "plan_id": plan_id,
        "action": "start",
        "state": "ACTIVE",
        "message": msg,
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })


@router.post("/action-sequences/plans/{plan_id}/pause", response_model=ApiResponse)
async def pause_plan(plan_id: str):
    """暂停执行行动序列 — 状态转移 + Zenoh control_mission (task_control=2)"""
    ok, msg = action_runtime.transit(plan_id, "PAUSED")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)

    zenoh_ok, zenoh_msg = publish_control_mission(plan_id, task_control=2)
    return ApiResponse(data={
        "plan_id": plan_id,
        "action": "pause",
        "state": "PAUSED",
        "message": msg,
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })


@router.post("/action-sequences/plans/{plan_id}/resume", response_model=ApiResponse)
async def resume_plan(plan_id: str):
    """继续执行行动序列 — 状态转移 + Zenoh control_mission (task_control=3)"""
    ok, msg = action_runtime.transit(plan_id, "ACTIVE")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)

    zenoh_ok, zenoh_msg = publish_control_mission(plan_id, task_control=3)
    return ApiResponse(data={
        "plan_id": plan_id,
        "action": "resume",
        "state": "ACTIVE",
        "message": msg,
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })


@router.post("/action-sequences/plans/{plan_id}/stop", response_model=ApiResponse)
async def stop_plan(plan_id: str):
    """停止/重置行动序列 — 状态重置 + Zenoh control_mission (task_control=4)"""
    action_runtime.reset(plan_id)

    zenoh_ok, zenoh_msg = publish_control_mission(plan_id, task_control=4)
    return ApiResponse(data={
        "plan_id": plan_id,
        "action": "stop",
        "state": "SCHEDULED",
        "message": "行动序列已停止并重置",
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })


@router.post("/action-sequences/plans/{plan_id}/dispatch-forward", response_model=ApiResponse)
async def dispatch_plan_forward_route(plan_id: str, body: DispatchForwardRequest):
    """协同席 — 将行动方案通过数据服务器 /ingestion/forward 下发到指定席位。"""
    result = dispatch_plan_forward(plan_id, body.target_ips, body.timeout_seconds or 30)
    if not result.get("ok"):
        return ApiResponse(code=500, message=result.get("error") or "下发失败", data=result)
    return ApiResponse(data=result)


@router.post("/action-sequences/plans/{plan_id}/dispatch", response_model=ApiResponse)
async def dispatch_plan(plan_id: str, body: DispatchRequest):
    """
    协同席 — 将行动方案下发到操控席数据服务端（POST /ingestion/import）。
    """
    plan = get_plan_detail(plan_id)
    if not plan:
        return ApiResponse(code=404, message="Plan not found", data=None)

    # 从 plan 详情中重建完整的资源对象用于 import
    plan_resource = {
        "resource_id": plan.get("resource_id") or f"plan:{plan_id}",
        "task_type": "PLAN",
        "plan_id": plan_id,
        "title": plan.get("title", ""),
        "description": plan.get("description", ""),
        "state": plan.get("state") or "DRAFT",
        "teams": plan.get("teams", []),
        "targets": plan.get("targets", []),
        "stages": plan.get("stages", []),
    }

    result = import_plan_to_operator(plan_resource)
    if result is None:
        return ApiResponse(code=500, message="下发到操控席数据服务端失败", data=None)

    return ApiResponse(data={
        "plan_id": plan_id,
        "action": "dispatch_to_operator",
        "imported": True,
        "message": "行动方案已下发到操控席数据服务端",
    })


# ========== 操控端行动序列专用接口 ==========

@router.get("/action-sequences/operator/connected-vehicles", response_model=ApiResponse)
async def list_connected_vehicles_operator():
    """操控端 — 从数据服务器资源池获取当前已连接车辆列表"""
    items = query_online_vehicles_operator()
    selected = vehicle_control_client.get_selected_vehicle_id()
    return ApiResponse(data={
        "items": items,
        "selected": selected,
        "total": len(items),
    })


@router.post("/action-sequences/operator/select-vehicle", response_model=ApiResponse)
async def select_vehicle_operator(body: SelectVehicleRequest):
    """操控端 — 选中一辆车并订阅 zenoh 反馈"""
    vehicle_id = body.vehicle_id
    clean_vid = vehicle_id.replace("equipment:", "")
    info = _find_online_vehicle_by_id(vehicle_id, query_online_vehicles_operator())
    if not info:
        return ApiResponse(code=404, message=f"车辆 {vehicle_id} 不在线或未找到", data=None)

    ok = zenoh_client.subscribe_vehicle_feedbacks(clean_vid)
    if ok:
        vehicle_control_client.set_selected_vehicle_id(vehicle_id)
        print(f"[AS-API-OP] selected vehicle: {vehicle_id}, subscribed feedbacks")
        return ApiResponse(data={
            "selected": vehicle_id,
            "info": info,
            "subscribed": True,
        })
    return ApiResponse(code=500, message=f"订阅车辆 {vehicle_id} 反馈失败", data={"selected": vehicle_id})


@router.get("/action-sequences/operator/vehicles", response_model=ApiResponse)
async def list_online_vehicles_operator():
    """操控端 — 从操控席数据服务端获取当前已连接的无人车列表"""
    items = query_online_vehicles_operator()
    return ApiResponse(data={"items": items, "total": len(items)})


@router.get("/action-sequences/operator/plans", response_model=ApiResponse)
async def list_plans_operator(limit: int = 200):
    """操控端 — 从操控席数据服务端获取行动方案列表"""
    items = query_plans_operator(limit=limit)
    return ApiResponse(data={"items": items, "total": len(items)})


@router.get("/action-sequences/operator/plans/{plan_id}", response_model=ApiResponse)
async def get_plan_operator(plan_id: str):
    """操控端 — 从操控席数据服务端获取方案详情"""
    detail = get_plan_detail_operator(plan_id)
    if not detail:
        return ApiResponse(code=404, message="Plan not found", data=None)
    runtime = action_runtime.get_state(detail.get("plan_id", plan_id))
    detail["runtime_state"] = runtime
    return ApiResponse(data=detail)


@router.post("/action-sequences/operator/plans/{plan_id}/dispatch", response_model=ApiResponse)
async def dispatch_plan_operator(plan_id: str, body: DispatchRequest):
    """
    操控端 — 通过 Zenoh 发送 MissionService/send_mission 到无人车。
    vehicle 从请求体取（默认 ZD04），mission_data 由 plan 详情拼装。
    """
    import json

    plan = get_plan_detail_operator(plan_id)
    if not plan:
        return ApiResponse(code=404, message="Plan not found", data=None)

    # 下发前先把本地 plan 同步到数据服务器
    sync_plan_to_operator(plan_id)

    vehicle_vid = body.vehicle_vid or get_first_vid(plan)
    # 去掉 equipment: 前缀（如 equipment:XL01 → XL01）
    vehicle_vid_clean = vehicle_vid.replace("equipment:", "") if vehicle_vid else vehicle_vid
    payload = build_mission_payload(
        plan,
        vehicle_vmfs=body.vehicle_vmfs,
        vehicle_ips=body.vehicle_ips,
        tid=body.tid,
        target_vid=vehicle_vid_clean,
    )
    topic = f"op/t01/g01/v{vehicle_vid_clean}/cmd/MissionService/send_mission"

    print(f"\n[DISPATCH-OP] ====== 操控端下发开始 ======")
    print(f"[DISPATCH-OP] plan_id={plan_id} | vehicle_vid={vehicle_vid_clean} | topic={topic}")
    print(f"[DISPATCH-OP] mission_payload={json.dumps(payload, ensure_ascii=False, indent=2)}")

    ok = zenoh_client.publish(topic, payload)
    print(f"[DISPATCH-OP] zenoh_publish result={ok}")
    if not ok:
        err = zenoh_client.get_last_zenoh_error()
        print(f"[DISPATCH-OP] zenoh error={err}")
        print(f"[DISPATCH-OP] ====== 下发结束(500) ======\n")
        return ApiResponse(code=500, message=f"Zenoh 下发失败: {err}", data={"topic": topic})

    print(f"[DISPATCH-OP] ====== 下发成功 ======\n")

    # 下发成功后，向任务监控服务注册车辆+行动+路线，并做出发前预检冲突
    monitoring_result = task_monitoring_client.register_mission_for_monitoring(
        plan_id, vehicle_vid_clean, plan
    )

    # 若预检发现冲突，立即推送一次提醒
    task_monitoring_client.send_warnings_if_any(
        plan_id,
        vehicle_vid_clean,
        "/conflict/validate",
        monitoring_result.get("route_validate"),
        plan_name=plan.get("title"),
    )

    return ApiResponse(data={
        "plan_id": plan_id,
        "action": "dispatch",
        "topic": topic,
        "vehicle_vid": vehicle_vid_clean,
        "mission_tid": payload["args"]["mission_data"]["task"]["tid"],
        "message": "任务已通过 Zenoh 下发",
        "task_monitoring": monitoring_result,
    })


@router.post("/action-sequences/operator/plans", response_model=ApiResponse)
async def create_plan_operator(plan: Dict[str, Any]):
    """操控端 — 新建行动序列方案并保存到本地 task_pool（同时尝试导入操控席数据服务器）"""
    saved = create_operator_plan(plan)
    return ApiResponse(data={
        "plan_id": saved.get("plan_id"),
        "resource_id": saved.get("resource_id"),
        "title": saved.get("title"),
        "state": saved.get("state"),
        "message": "方案已保存",
    })


@router.patch("/action-sequences/plans/{plan_id}", response_model=ApiResponse)
async def patch_plan(plan_id: str, body: Dict[str, Any]):
    """协同席 — 仅更新本地 task_pool 中的方案，不同步到数据服务器"""
    saved = update_plan(plan_id, body)
    if not saved:
        return ApiResponse(code=404, message="Plan not found", data=None)
    return ApiResponse(data=saved)


@router.post("/action-sequences/plans/{plan_id}/vehicles/{vid}/delete", response_model=ApiResponse)
async def delete_vehicle_from_plan(plan_id: str, vid: str):
    """协同席 — 删除方案中指定车辆的行动序列。

    会先把数据服务器上该车辆对应的所有 action / car_action 状态置为 DELETED，
    再更新本地 plan 并同步到数据服务器。
    """
    result = delete_vehicle(plan_id, vid)
    if not result.get("ok"):
        return ApiResponse(code=500, message=result.get("error") or "删除失败", data=result)
    return ApiResponse(data=result)


@router.patch("/action-sequences/operator/plans/{plan_id}", response_model=ApiResponse)
async def patch_plan_operator(plan_id: str, body: Dict[str, Any]):
    """操控端 — 更新方案并保存到操控席数据服务器（使用 import 全量保存，确保 stages/team_actions 落盘）"""
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    # 1. 先检查 plan 是否存在
    data = _http_get_operator(f"/api/v1/task_pool/resources/simple/{rid}", silent=True)
    if data is None or not isinstance(data, dict):
        return ApiResponse(code=404, message="Plan not found", data=None)

    # 2. 使用请求体作为完整 plan 数据，确保包含 stages/team_actions
    # 前端发送的请求体已经是完整 plan 结构，直接使用
    plan = _normalize_plan_field_names(body)
    plan["resource_id"] = rid
    plan["task_type"] = "PLAN"
    plan["plan_id"] = plan_id
    plan["updated_at"] = datetime.now(timezone.utc).isoformat()

    # 3. 使用 import 接口全量保存，确保 stages/team_actions 等嵌套数据正确落盘
    result = _http_post_operator(
        "/api/v1/task_pool/ingestion/import",
        {"resources": [_scale_coords_to_int(plan)], "return_data_type": "typed", "ignore_errors": True},
        silent=True,
    )
    if result is None:
        return ApiResponse(code=500, message="保存到数据服务器失败", data=None)

    # 4. 返回更新后的 plan 详情
    updated = _http_get_operator(f"/api/v1/task_pool/resources/simple/{rid}", silent=True)
    if updated is None or not isinstance(updated, dict):
        return ApiResponse(code=500, message="保存成功但获取更新后数据失败", data=None)
    return ApiResponse(data=_normalize_plan_field_names(updated))


@router.post("/action-sequences/operator/plans/{plan_id}/vehicles/{vid}/delete", response_model=ApiResponse)
async def delete_vehicle_from_plan_operator(plan_id: str, vid: str):
    """操控端 — 删除方案中指定车辆的行动序列。

    会先把数据服务器上该车辆对应的所有 action / car_action 状态置为 DELETED，
    再更新本地 plan 并同步到数据服务器。
    """
    result = delete_vehicle_operator(plan_id, vid)
    if not result.get("ok"):
        return ApiResponse(code=500, message=result.get("error") or "删除失败", data=result)
    return ApiResponse(data=result)


@router.post("/action-sequences/operator/plans/{plan_id}/sync", response_model=ApiResponse)
async def sync_plan_operator(plan_id: str):
    """操控端 — 把本地 task_pool 中的 plan 同步到数据服务器"""
    ok = sync_plan_to_operator(plan_id)
    if not ok:
        return ApiResponse(code=500, message="同步到数据服务器失败", data=None)
    return ApiResponse(data={
        "plan_id": plan_id,
        "action": "sync_to_operator",
        "message": "方案已同步到数据服务器",
    })


@router.post("/action-sequences/operator/plans/{plan_id}/start", response_model=ApiResponse)
async def start_plan_operator(plan_id: str, vehicle_vid: Optional[str] = Query(None)):
    """操控端 — 开始执行 — Zenoh control_mission (task_control=1)"""
    ok, msg = action_runtime.transit(plan_id, "ACTIVE")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)
    zenoh_ok, zenoh_msg = publish_control_mission(plan_id, task_control=1, vehicle_vid=vehicle_vid)

    # Zenoh 控制指令下发成功后，启动任务监控轮询（每 5 秒上报一次绿色接口）
    if zenoh_ok:
        plan = get_plan_detail_operator(plan_id)
        target_vid = vehicle_vid or get_first_vid(plan) if plan else vehicle_vid
        target_vid_clean = target_vid.replace("equipment:", "") if target_vid else target_vid
        if plan and target_vid_clean:
            task_monitoring_client.start_monitoring(plan_id, target_vid_clean, plan)

    return ApiResponse(data={
        "plan_id": plan_id, "action": "start", "state": "ACTIVE", "message": msg,
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })


@router.post("/action-sequences/operator/plans/{plan_id}/pause", response_model=ApiResponse)
async def pause_plan_operator(plan_id: str, vehicle_vid: Optional[str] = Query(None)):
    """操控端 — 暂停执行 — Zenoh control_mission (task_control=2)"""
    ok, msg = action_runtime.transit(plan_id, "PAUSED")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)
    zenoh_ok, zenoh_msg = publish_control_mission(plan_id, task_control=2, vehicle_vid=vehicle_vid)
    return ApiResponse(data={
        "plan_id": plan_id, "action": "pause", "state": "PAUSED", "message": msg,
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })


@router.post("/action-sequences/operator/plans/{plan_id}/resume", response_model=ApiResponse)
async def resume_plan_operator(plan_id: str, vehicle_vid: Optional[str] = Query(None)):
    """操控端 — 继续执行 — Zenoh control_mission (task_control=3)"""
    ok, msg = action_runtime.transit(plan_id, "ACTIVE")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)
    zenoh_ok, zenoh_msg = publish_control_mission(plan_id, task_control=3, vehicle_vid=vehicle_vid)
    return ApiResponse(data={
        "plan_id": plan_id, "action": "resume", "state": "ACTIVE", "message": msg,
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })


@router.post("/action-sequences/operator/plans/{plan_id}/stop", response_model=ApiResponse)
async def stop_plan_operator(plan_id: str, vehicle_vid: Optional[str] = Query(None)):
    """操控端 — 停止/重置 — Zenoh control_mission (task_control=4)"""
    action_runtime.reset(plan_id)
    zenoh_ok, zenoh_msg = publish_control_mission(plan_id, task_control=4, vehicle_vid=vehicle_vid)

    # 停止对应任务监控轮询
    target_vid = vehicle_vid
    if not target_vid:
        plan = get_plan_detail_operator(plan_id)
        target_vid = get_first_vid(plan) if plan else None
    target_vid_clean = target_vid.replace("equipment:", "") if target_vid else None
    if target_vid_clean:
        task_monitoring_client.stop_monitoring(plan_id, target_vid_clean)

    return ApiResponse(data={
        "plan_id": plan_id, "action": "stop", "state": "SCHEDULED",
        "message": "行动序列已停止并重置",
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })


@router.post("/action-sequences/local/clear", response_model=ApiResponse)
async def clear_local_task_pool():
    """清空本地 task_pool 缓存（开发调试用）"""
    result = task_pool.clear()
    return ApiResponse(data={
        "action": "clear_local_task_pool",
        "cleared": result.get("cleared", 0),
        "message": f"已清空本地 task_pool，共 {result.get('cleared', 0)} 条记录",
    })


@router.get("/action-sequences/events")
async def action_sequence_events(request: Request):
    """行动序列 SSE 事件流：推送 plan 内容变化和数量增删通知"""
    q = sse_manager.register_overview(PLAN_SSE_SCOPE)

    async def generate():
        async for chunk in sse_manager.event_generator(q):
            yield chunk
        sse_manager.unregister_overview(PLAN_SSE_SCOPE, q)

    return StreamingResponse(generate(), media_type="text/event-stream")
