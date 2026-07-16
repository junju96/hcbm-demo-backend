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
from fastapi import APIRouter, Query

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
    get_online_vehicle_info_from_resource_pool,
    delete_vehicle_operator,
    delete_vehicle,
    dispatch_plan_forward,
)
from app.services import zenoh_client
from app.services.task_pool import task_pool
from app.services import vehicle_control_client

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
    """获取车辆控制服务当前已连接车辆列表（用于操控席选择车辆）"""
    items = vehicle_control_client.get_all_vehicle_info()
    selected = vehicle_control_client.get_selected_vehicle_id()
    return ApiResponse(data={
        "items": items,
        "selected": selected,
        "total": len(items),
    })


@router.get("/action-sequences/selected-vehicle", response_model=ApiResponse)
async def get_selected_vehicle():
    """获取当前已选中的车辆"""
    selected = vehicle_control_client.get_selected_vehicle_id()
    info = vehicle_control_client.get_selected_vehicle_info()
    return ApiResponse(data={
        "selected": selected,
        "info": info,
    })


@router.post("/action-sequences/select-vehicle", response_model=ApiResponse)
async def select_vehicle(body: SelectVehicleRequest):
    """选中一辆车：刷新缓存、订阅该车辆 zenoh 反馈、记录选中状态"""
    vehicle_id = body.vehicle_id
    # 先刷新一次车辆信息，确保车辆当前在线
    vehicle_control_client.refresh_vehicle_info()
    info = vehicle_control_client.get_vehicle_info(vehicle_id)
    if not info:
        return ApiResponse(code=404, message=f"车辆 {vehicle_id} 不在线或未找到", data=None)

    # 订阅该车辆反馈
    ok = zenoh_client.subscribe_vehicle_feedbacks(vehicle_id.replace("equipment:", ""))
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
    """操控端 — 获取车辆控制服务当前已连接车辆列表。

    车辆控制服务（28009）与资源池（28800）可能不同步，
    因此以资源池 online 车辆为准做合并兜底，确保新上线车辆（如 HL01）能显示，
    已下线车辆（如 XL01）不显示。
    """
    # 1) 车辆控制服务缓存（用于展示 VMF/IP 等实时信息）
    control_items = vehicle_control_client.get_all_vehicle_info()
    control_map = {}
    for item in control_items:
        vid = item.get("vid") or item.get("vehicle_id") or ""
        if vid:
            control_map[vid.replace("equipment:", "")] = item

    # 2) 资源池在线车辆（权威在线状态）
    resource_pool_items = query_online_vehicles_operator()
    merged = []
    seen = set()
    for v in resource_pool_items:
        vid = (v.get("vid") or "").replace("equipment:", "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        # 优先用车辆控制服务的实时信息，没有则用资源池信息兜底
        control = control_map.get(vid)
        if control:
            merged.append({
                "vid": f"equipment:{vid}",
                "name": control.get("name") or v.get("display_name") or v.get("resource_name") or vid,
                "resource_name": v.get("resource_name") or control.get("name") or vid,
                "vmf": control.get("VMF") or control.get("vmf") or v.get("vmf"),
                "ip": control.get("ip") or v.get("ip") or "25.11.1.1",
            })
        else:
            merged.append({
                "vid": f"equipment:{vid}",
                "name": v.get("display_name") or v.get("resource_name") or vid,
                "resource_name": v.get("resource_name") or vid,
                "vmf": v.get("vmf"),
                "ip": v.get("ip") or "25.11.1.1",
            })

    selected = vehicle_control_client.get_selected_vehicle_id()
    return ApiResponse(data={
        "items": merged,
        "selected": selected,
        "total": len(merged),
    })


@router.post("/action-sequences/operator/select-vehicle", response_model=ApiResponse)
async def select_vehicle_operator(body: SelectVehicleRequest):
    """操控端 — 选中一辆车并订阅 zenoh 反馈。

    车辆控制服务（28009）未同步时，以资源池在线车辆信息兜底，
    避免新上线车辆（如 HL01）因不在车辆控制服务缓存中而无法被选中。
    """
    vehicle_id = body.vehicle_id
    clean_vid = vehicle_id.replace("equipment:", "")
    vehicle_control_client.refresh_vehicle_info()
    info = vehicle_control_client.get_vehicle_info(vehicle_id)

    if not info:
        # 车辆控制服务缓存缺失：尝试从资源池兜底并注入缓存
        rp_info = get_online_vehicle_info_from_resource_pool(vehicle_id)
        if not rp_info:
            return ApiResponse(code=404, message=f"车辆 {vehicle_id} 不在线或未找到", data=None)
        info = vehicle_control_client.ensure_vehicle_info(
            vehicle_id,
            vmf=rp_info.get("vmf"),
            ip=rp_info.get("ip") or "25.11.1.1",
            name=rp_info.get("display_name") or rp_info.get("resource_name") or clean_vid,
            vehicle_type=rp_info.get("resource_type"),
        )

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
    return ApiResponse(data={
        "plan_id": plan_id,
        "action": "dispatch",
        "topic": topic,
        "vehicle_vid": vehicle_vid_clean,
        "mission_tid": payload["args"]["mission_data"]["task"]["tid"],
        "message": "任务已通过 Zenoh 下发",
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
    """操控端 — 仅更新本地 task_pool 中的方案，不同步到数据服务器"""
    saved = update_operator_plan_locally(plan_id, body)
    if not saved:
        return ApiResponse(code=404, message="Plan not found", data=None)
    return ApiResponse(data=saved)


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
    return ApiResponse(data={
        "plan_id": plan_id, "action": "stop", "state": "SCHEDULED",
        "message": "行动序列已停止并重置",
        "zenoh": {"ok": zenoh_ok, "message": zenoh_msg},
    })
