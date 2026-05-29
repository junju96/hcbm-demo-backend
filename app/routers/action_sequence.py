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
from fastapi import APIRouter

from pydantic import BaseModel
from typing import Any, Dict, Optional

from app.models.schemas import ApiResponse
from app.services.action_sequence_client import (
    query_plans,
    get_plan_detail,
    action_runtime,
    build_mission_payload,
)
from app.services import zenoh_client

router = APIRouter()


@router.get("/action-sequences/plans", response_model=ApiResponse)
async def list_plans(limit: int = 20):
    """获取行动方案列表"""
    items = query_plans(limit=limit)
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


@router.post("/action-sequences/plans/{plan_id}/start", response_model=ApiResponse)
async def start_plan(plan_id: str):
    """开始执行行动序列"""
    ok, msg = action_runtime.transit(plan_id, "ACTIVE")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)
    return ApiResponse(data={"plan_id": plan_id, "action": "start", "state": "ACTIVE", "message": msg})


@router.post("/action-sequences/plans/{plan_id}/pause", response_model=ApiResponse)
async def pause_plan(plan_id: str):
    """暂停执行行动序列"""
    ok, msg = action_runtime.transit(plan_id, "PAUSED")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)
    return ApiResponse(data={"plan_id": plan_id, "action": "pause", "state": "PAUSED", "message": msg})


@router.post("/action-sequences/plans/{plan_id}/resume", response_model=ApiResponse)
async def resume_plan(plan_id: str):
    """继续执行行动序列"""
    ok, msg = action_runtime.transit(plan_id, "ACTIVE")
    if not ok:
        return ApiResponse(code=400, message=msg, data=None)
    return ApiResponse(data={"plan_id": plan_id, "action": "resume", "state": "ACTIVE", "message": msg})


class DispatchRequest(BaseModel):
    vehicle_vmfs: Optional[Dict[str, int]] = None
    vehicle_ips: Optional[Dict[str, str]] = None
    tid: Optional[int] = None
    vehicle_topic: Optional[str] = "ZD04"


@router.post("/action-sequences/plans/{plan_id}/stop", response_model=ApiResponse)
async def stop_plan(plan_id: str):
    """停止/重置行动序列"""
    action_runtime.reset(plan_id)
    return ApiResponse(data={"plan_id": plan_id, "action": "stop", "state": "SCHEDULED", "message": "行动序列已停止并重置"})


@router.post("/action-sequences/plans/{plan_id}/dispatch", response_model=ApiResponse)
async def dispatch_plan(plan_id: str, body: DispatchRequest):
    """
    下发行动序列到无人车（通过 Zenoh 发送 MissionService/send_mission）。

    请求体可选字段：
      - vehicle_vmfs: {"无人车A": 99076716, ...}  — vid 到 vmf 数字编号映射
      - vehicle_ips:  {"无人车A": "192.168.1.11", ...}  — vid 到 IP 映射
      - tid: 任务编号，默认从 plan_id 推导
      - vehicle_topic: 目标车辆 topic 后缀，默认 ZD04
    """
    import json

    print(f"\n[DISPATCH] ====== 行动序列下发开始 ======")
    print(f"[DISPATCH] plan_id={plan_id}")
    print(f"[DISPATCH] request_body={body.model_dump_json()}")

    # 1. 获取 plan 详情
    plan = get_plan_detail(plan_id)
    if not plan:
        print(f"[DISPATCH] Plan not found: {plan_id}")
        print(f"[DISPATCH] ====== 下发结束(404) ======\n")
        return ApiResponse(code=404, message="Plan not found", data=None)

    print(f"[DISPATCH] plan found, title={plan.get('title', '')}, stages={len(plan.get('stages', []))}")

    # 2. 构建 mission payload
    payload = build_mission_payload(
        plan,
        vehicle_vmfs=body.vehicle_vmfs,
        vehicle_ips=body.vehicle_ips,
        tid=body.tid,
    )
    print(f"[DISPATCH] mission_payload={json.dumps(payload, ensure_ascii=False, indent=2)}")

    # 3. 构造 zenoh topic
    vehicle = (body.vehicle_topic or "ZD04").strip()
    topic = f"op/t01/g01/v{vehicle}/cmd/MissionService/send_mission"
    print(f"[DISPATCH] zenoh_topic={topic}")

    # 4. 通过 zenoh 发布
    ok = zenoh_client.publish(topic, payload)
    print(f"[DISPATCH] zenoh_publish result={ok}")
    if not ok:
        err = zenoh_client.get_last_zenoh_error()
        print(f"[DISPATCH] zenoh error={err}")
        print(f"[DISPATCH] ====== 下发结束(500) ======\n")
        return ApiResponse(code=500, message=f"Zenoh 下发失败: {err}", data={"topic": topic})

    print(f"[DISPATCH] ====== 下发成功 ======\n")
    return ApiResponse(
        data={
            "plan_id": plan_id,
            "action": "dispatch",
            "topic": topic,
            "mission_tid": payload["args"]["mission_data"]["task"]["tid"],
            "message": "任务已通过 Zenoh 下发",
        }
    )
