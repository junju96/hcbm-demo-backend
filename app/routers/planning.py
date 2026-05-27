"""
规划事件流路由 — SSE overview + detail
"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import StreamingResponse
from typing import Optional

from app.services.sse_manager import sse_manager

router = APIRouter()


@router.get("/planning/events/overview")
async def planning_events_overview(
    request: Request,
    client_id: str = Query(..., description="前端客户端标识"),
    scope: str = Query(..., description="作用域，如 planning_home / command_decomposition"),
):
    """摘要 SSE 流：推送命令/任务/方案/杀伤链卡片摘要"""
    q = sse_manager.register_overview(scope)

    # 立即推送初始化事件
    from app.services.task_pool import task_pool
    from app.services.data_server_client import query_kill_chains, to_frontend_killchain_list
    all_resources = task_pool.all()

    commands = []
    missions = []
    plans = []
    kill_chains = []

    # KILL_CHAIN 从数据服务器获取
    try:
        ds_items = query_kill_chains(limit=50)
        kill_chains = to_frontend_killchain_list(ds_items)
    except Exception:
        pass

    for res in all_resources.values():
        summary = {"resource_id": res.get("resource_id"), "title": res.get("title", ""), "state": res.get("state", "INIT")}
        tt = res.get("task_type", "")
        if tt == "COMMAND":
            commands.append(summary)
        elif tt == "MISSION":
            missions.append(summary)
        elif tt == "PLAN":
            plans.append(summary)

    init_data = {
        "commands": commands,
        "missions": missions,
        "plans": plans,
        "kill_chains": kill_chains,
    }
    await q.put({"event": "planning.overview.init", "data": init_data})

    async def generate():
        async for chunk in sse_manager.event_generator(q):
            yield chunk
        sse_manager.unregister_overview(scope, q)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/planning/events/detail")
async def planning_events_detail(
    request: Request,
    resource_type: str = Query(..., description="资源类型: command/mission/plan/kill_chain"),
    resource_id: str = Query(..., description="资源ID"),
    client_id: str = Query(..., description="前端客户端标识"),
):
    """详情 SSE 流：推送当前选中资源的全量详情"""
    q = sse_manager.register_detail(resource_type, resource_id)

    # 立即推送初始化事件
    from app.services.task_pool import task_pool
    from app.services.data_server_client import get_kill_chain
    detail = None
    if resource_type.lower() == "kill_chain":
        detail = get_kill_chain(resource_id)
    if not detail:
        detail = task_pool.get(resource_id)
    if detail:
        init_data = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "detail": detail,
        }
        await q.put({"event": "planning.detail.init", "data": init_data})

    async def generate():
        async for chunk in sse_manager.event_generator(q):
            yield chunk
        sse_manager.unregister_detail(resource_type, resource_id, q)

    return StreamingResponse(generate(), media_type="text/event-stream")
