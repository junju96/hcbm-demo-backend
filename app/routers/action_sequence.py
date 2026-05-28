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

from app.models.schemas import ApiResponse
from app.services.action_sequence_client import (
    query_plans,
    get_plan_detail,
    action_runtime,
)

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


@router.post("/action-sequences/plans/{plan_id}/stop", response_model=ApiResponse)
async def stop_plan(plan_id: str):
    """停止/重置行动序列"""
    action_runtime.reset(plan_id)
    return ApiResponse(data={"plan_id": plan_id, "action": "stop", "state": "SCHEDULED", "message": "行动序列已停止并重置"})
