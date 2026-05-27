"""
杀伤链路由 — Kill Chain API
"""

import uuid
import asyncio
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException
from typing import List, Optional, Dict, Any

from app.models.schemas import (
    KillChainCreate, KillChainUpdate, KillChainEntryCreate,
    ResourceAllocate, AutoAllocateRequest, GeneratePlanRequest,
    ResourceQuery, ApiResponse,
)
from app.services.task_pool import task_pool
from app.services.sse_manager import sse_manager

router = APIRouter()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _get_kill_chain(kill_chain_id: str):
    """获取杀伤链，支持带前缀或不带前缀"""
    rid = kill_chain_id if kill_chain_id.startswith("kill_chain:") else f"kill_chain:{kill_chain_id}"
    kc = task_pool.get(rid)
    if not kc:
        raise HTTPException(status_code=404, detail=f"KillChain not found: {kill_chain_id}")
    return kc, rid


def _build_resource_candidates(operation: str, keyword: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """根据作战动作查询候选装备（mock 推荐逻辑）"""
    all_resources = task_pool.all()
    candidates = []

    # 作战动作 -> 能力匹配关键词
    op_keywords = {
        "侦察": ["recon_range_km"],
        "定位": ["recon_range_km"],
        "跟踪": ["recon_range_km"],
        "瞄准/引导": ["strike_range_km"],
        "打击": ["strike_range_km", "weapon"],
        "评估": ["recon_range_km"],
    }

    for res in all_resources.values():
        if res.get("task_type") != "EQUIPMENT":
            continue
        cap = res.get("capacity", {})
        note = ""
        locked = False

        # 简单匹配逻辑
        if operation in ["侦察", "定位", "跟踪", "评估"]:
            if cap.get("recon_range_km", 0) > 0:
                note = f"合法；{res['resource_name']}具备侦察能力"
            else:
                note = f"不推荐；{res['resource_name']}侦察能力弱"
                locked = True
        elif operation in ["瞄准/引导", "打击"]:
            if cap.get("strike_range_km", 0) > 0:
                note = f"合法；{res['resource_name']}具备打击能力"
            else:
                note = f"不推荐；{res['resource_name']}打击能力弱"
                locked = True
        else:
            note = f"合法；{res['resource_name']}可作为备选"

        if keyword and keyword.lower() not in res.get("resource_name", "").lower():
            continue

        candidates.append({
            "executor_id": res["resource_id"],
            "resource_name": res.get("resource_name", ""),
            "resource_type": res.get("resource_type", ""),
            "allocation_count": 0,
            "locked": locked,
            "note": note,
        })

    # 合法资源排前面
    candidates.sort(key=lambda x: (x["locked"], x["resource_name"]))
    return candidates[:limit]


# ========== 杀伤链 CRUD ==========

@router.post("/kill-chains", response_model=ApiResponse)
async def create_kill_chain(req: Request, body: KillChainCreate):
    """创建杀伤链"""
    kc_id = _new_id("kc")
    rid = f"kill_chain:{kc_id}"

    target_ids = [t.get("target_id", "") for t in body.targets]
    target_display = {f"target:{t.get('target_id')}": t.get("target_name", t.get("target_id", "")) for t in body.targets}

    now = datetime.now(timezone.utc).isoformat()
    kill_chain = {
        "resource_id": rid,
        "task_type": "KILL_CHAIN",
        "kill_chain_id": kc_id,
        "title": body.title,
        "description": body.description,
        "state": "INIT",
        "resource_ids": [],
        "target_ids": target_ids,
        "mapped_plan_ids": [],
        "connections": [],
        "dependencies": [],
        "relations": [],
        "attributes": {
            "created_from": "api",
            "target_display": target_display,
        },
        "raw_entries": [],
        "assigned_entries": [],
        "mapping_summary": {},
        "network": {"nodes": [], "edges": []},
        "search_text": body.title + " " + body.description,
        "created_at": now,
        "updated_at": now,
    }

    task_pool.set(rid, kill_chain)

    # SSE 推送
    await sse_manager.push_overview_changed(
        "planning_home", "KILL_CHAIN", rid,
        summary={"title": body.title, "state": "INIT"},
        action="CREATE",
    )

    return ApiResponse(data={"kill_chain_id": kc_id, "resource_id": rid, "status": "created"})


@router.get("/kill-chains/{kill_chain_id}", response_model=ApiResponse)
async def get_kill_chain(kill_chain_id: str):
    """获取杀伤链详情"""
    kc, rid = _get_kill_chain(kill_chain_id)
    return ApiResponse(data=kc)


@router.patch("/kill-chains/{kill_chain_id}", response_model=ApiResponse)
async def update_kill_chain(kill_chain_id: str, body: KillChainUpdate):
    """更新杀伤链"""
    kc, rid = _get_kill_chain(kill_chain_id)

    payload = body.model_dump(exclude_none=True)
    if not payload:
        return ApiResponse(data=kc)

    updated = task_pool.patch(rid, payload)

    # SSE 推送
    await sse_manager.push_kill_chain_detail(rid, "planning.detail.changed", updated, "杀伤链内容已更新")
    await sse_manager.push_overview_changed(
        "planning_home", "KILL_CHAIN", rid,
        summary={"title": updated.get("title", ""), "state": updated.get("state", "")},
    )

    return ApiResponse(data=updated)


@router.delete("/kill-chains/{kill_chain_id}", response_model=ApiResponse)
async def delete_kill_chain(kill_chain_id: str):
    """删除杀伤链"""
    kc, rid = _get_kill_chain(kill_chain_id)
    task_pool.update_lifecycle(rid, "DELETED", "user_deleted")

    await sse_manager.push_overview_changed(
        "planning_home", "KILL_CHAIN", rid,
        summary={"title": kc.get("title", ""), "state": "DELETED"},
        action="DELETE",
    )

    return ApiResponse(data={"kill_chain_id": kill_chain_id, "result": "success"})


@router.post("/kill-chains/{kill_chain_id}/forward", response_model=ApiResponse)
async def forward_kill_chain(kill_chain_id: str, body: Dict[str, str]):
    """转发杀伤链"""
    kc, rid = _get_kill_chain(kill_chain_id)
    target = body.get("target", "")
    return ApiResponse(data={"kill_chain_id": kill_chain_id, "result": "success", "target": target})


# ========== Entries 管理 ==========

@router.post("/kill-chains/{kill_chain_id}/entries", response_model=ApiResponse)
async def add_entry(kill_chain_id: str, body: KillChainEntryCreate):
    """增加杀伤链条目"""
    kc, rid = _get_kill_chain(kill_chain_id)

    entry_id = _new_id("entry")
    entry = {
        "entry_id": entry_id,
        "phase": "RAW",
        "entry_seq": body.entry_seq,
        "target_ids": body.target_ids,
        "operation": body.operation,
        "executor_options": _build_resource_candidates(body.operation),
        "selected_executor": None,
        "locked": False,
        "is_valid": True,
        "notes": body.notes,
    }

    raw_entries = kc.get("raw_entries", []) + [entry]
    updated = task_pool.patch(rid, {"raw_entries": raw_entries})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.entries_changed", updated, "杀伤链条目已增加")

    return ApiResponse(data={"entry_id": entry_id, "kill_chain_id": kill_chain_id})


@router.delete("/kill-chains/{kill_chain_id}/entries/{entry_id}", response_model=ApiResponse)
async def delete_entry(kill_chain_id: str, entry_id: str):
    """删除杀伤链条目"""
    kc, rid = _get_kill_chain(kill_chain_id)

    raw_entries = [e for e in kc.get("raw_entries", []) if e.get("entry_id") != entry_id]
    assigned_entries = [e for e in kc.get("assigned_entries", []) if e.get("entry_id") != entry_id]

    updated = task_pool.patch(rid, {"raw_entries": raw_entries, "assigned_entries": assigned_entries})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.entries_changed", updated, "杀伤链条目已删除")

    return ApiResponse(data={"entry_id": entry_id, "result": "success"})


# ========== 资源查询与分配 ==========

@router.post("/kill-chains/resources/query", response_model=ApiResponse)
async def query_resources(body: ResourceQuery):
    """查询候选装备"""
    candidates = _build_resource_candidates(
        operation=body.operation or "",
        keyword=body.keyword,
        limit=body.limit,
    )
    return ApiResponse(data={"items": candidates, "total": len(candidates)})


@router.post("/kill-chains/{kill_chain_id}/entries/{entry_id}/auto-allocate", response_model=ApiResponse)
async def auto_allocate(kill_chain_id: str, entry_id: str, body: AutoAllocateRequest):
    """自动分配资源"""
    kc, rid = _get_kill_chain(kill_chain_id)

    # 找到条目
    raw_entries = kc.get("raw_entries", [])
    entry = next((e for e in raw_entries if e.get("entry_id") == entry_id), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry not found: {entry_id}")

    # mock 自动分配：选第一个未锁定的候选
    options = entry.get("executor_options", [])
    chosen = next((o for o in options if not o.get("locked")), None)

    if not chosen:
        return ApiResponse(code=400, message="无可用的自动分配候选", data=None)

    # 构建 assigned entry
    assigned_entry = {
        "entry_id": _new_id("assigned"),
        "phase": "ASSIGNED",
        "entry_seq": entry["entry_seq"],
        "target_ids": entry["target_ids"],
        "operation": entry["operation"],
        "executor_options": [{
            **chosen,
            "allocation_count": chosen.get("allocation_count", 0) + 1,
            "locked": True,
            "note": f"自动分配选中{chosen.get('resource_name', chosen['executor_id'])}",
        }],
        "selected_executor": chosen["executor_id"],
        "locked": True,
        "is_valid": True,
        "notes": "自动分配完成",
    }

    assigned_entries = kc.get("assigned_entries", []) + [assigned_entry]
    updated = task_pool.patch(rid, {"assigned_entries": assigned_entries})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.resource_allocated", updated, "自动分配完成")

    return ApiResponse(data={
        "job_id": _new_id("auto-alloc"),
        "kill_chain_id": kill_chain_id,
        "entry_id": entry_id,
        "selected_executor": chosen["executor_id"],
        "status": "SUCCEEDED",
    })


@router.post("/kill-chains/{kill_chain_id}/entries/{entry_id}/allocate", response_model=ApiResponse)
async def manual_allocate(kill_chain_id: str, entry_id: str, body: ResourceAllocate):
    """人工分配资源"""
    kc, rid = _get_kill_chain(kill_chain_id)

    # 获取资源名称
    res = task_pool.get(body.selected_executor)
    resource_name = res.get("resource_name", body.selected_executor) if res else body.selected_executor

    assigned_entry = {
        "entry_id": _new_id("assigned"),
        "phase": "ASSIGNED",
        "entry_seq": 0,  # 实际应从原始条目继承
        "target_ids": [],
        "operation": "",
        "executor_options": [{
            "executor_id": body.selected_executor,
            "allocation_count": 1,
            "locked": True,
            "note": f"人工分配选中{resource_name}",
        }],
        "selected_executor": body.selected_executor,
        "locked": True,
        "is_valid": True,
        "notes": body.reason or "人工分配",
    }

    # 查找原始条目补充信息
    raw_entries = kc.get("raw_entries", [])
    raw_entry = next((e for e in raw_entries if e.get("entry_id") == entry_id), None)
    if raw_entry:
        assigned_entry["entry_seq"] = raw_entry["entry_seq"]
        assigned_entry["target_ids"] = raw_entry["target_ids"]
        assigned_entry["operation"] = raw_entry["operation"]

    assigned_entries = kc.get("assigned_entries", []) + [assigned_entry]
    updated = task_pool.patch(rid, {"assigned_entries": assigned_entries})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.resource_allocated", updated, "人工分配完成")

    return ApiResponse(data={
        "kill_chain_id": kill_chain_id,
        "entry_id": entry_id,
        "selected_executor": body.selected_executor,
        "result": "success",
    })


# ========== 方案生成 ==========

@router.post("/kill-chains/{kill_chain_id}/generate-plan", response_model=ApiResponse)
async def generate_plan(kill_chain_id: str, body: GeneratePlanRequest):
    """生成行动方案"""
    kc, rid = _get_kill_chain(kill_chain_id)

    # 过滤已分配条目
    assigned = kc.get("assigned_entries", [])
    selected = [e for e in assigned if e.get("entry_id") in body.selected_entry_ids]

    # mock 生成方案
    plan_id = _new_id("plan")
    plan_rid = f"plan:{plan_id}"
    now = datetime.now(timezone.utc).isoformat()

    # 按装备分组生成 team
    executor_map: Dict[str, List[Dict]] = {}
    for e in selected:
        ex = e.get("selected_executor", "")
        if ex not in executor_map:
            executor_map[ex] = []
        executor_map[ex].append(e)

    teams = []
    for i, (ex_id, entries) in enumerate(executor_map.items()):
        res = task_pool.get(ex_id)
        name = res.get("resource_name", ex_id) if res else ex_id
        teams.append({
            "task_type": "TEAM",
            "team_id": f"team-{i+1}",
            "name": f"{name}组",
            "plan_id": plan_rid,
            "description": f"由{name}组成，负责{', '.join(set(e['operation'] for e in entries))}",
            "equipment": [ex_id],
            "state": "READY",
        })

    plan = {
        "resource_id": plan_rid,
        "task_type": "PLAN",
        "plan_id": plan_id,
        "title": body.plan_config.get("title", "杀伤链映射行动方案"),
        "description": body.plan_config.get("description", f"由 {rid} 映射生成的行动方案"),
        "state": "DRAFT_EDITING",
        "attributes": {"plan_type": "KILL_CHAIN_GENERATED", "source_kill_chain_id": rid},
        "relations": [{"type": "generated_from", "target": rid, "metadata": {}}],
        "connections": [{"connection_type": "KILL_CHAIN", "connection_data": [rid]}],
        "teams": teams,
        "targets": [],
        "stages": [{
            "task_type": "STAGE",
            "stage_id": f"stage-{plan_id}",
            "title": "杀伤链执行阶段",
            "plan_id": plan_rid,
            "stage_seq": 1,
            "target_ids": list(set(tid for e in selected for tid in e.get("target_ids", []))),
            "team_ids": [t["team_id"] for t in teams],
            "state": "SCHEDULED",
        }],
        "search_text": body.plan_config.get("title", "杀伤链映射行动方案"),
        "created_at": now,
        "updated_at": now,
    }

    task_pool.set(plan_rid, plan)

    # 更新杀伤链的映射关系
    mapped_plan_ids = kc.get("mapped_plan_ids", []) + [plan_rid]
    mapping_summary = {
        "total_raw_entries": len(kc.get("raw_entries", [])),
        "total_assigned_entries": len(assigned),
        "target_count": len(kc.get("target_ids", [])),
        "resource_count": len(kc.get("resource_ids", [])),
        "generated_plan_resource_id": plan_rid,
    }
    updated_kc = task_pool.patch(rid, {
        "mapped_plan_ids": mapped_plan_ids,
        "mapping_summary": mapping_summary,
    })

    # SSE 推送
    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.plan_generated", updated_kc, "方案生成完成")
    await sse_manager.push_overview_changed(
        "planning_home", "PLAN", plan_rid,
        summary={"title": plan["title"], "state": plan["state"]},
        action="CREATE",
    )

    return ApiResponse(data={
        "plan_id": plan_rid,
        "kill_chain_id": kill_chain_id,
        "status": "SUCCEEDED",
        "message": "方案生成完成",
    })


# ========== 激活 / 静默 / 重映射 ==========

@router.post("/kill-chains/{kill_chain_id}/activate", response_model=ApiResponse)
async def activate_kill_chain(kill_chain_id: str):
    """激活杀伤链"""
    kc, rid = _get_kill_chain(kill_chain_id)
    updated = task_pool.patch(rid, {
        "state": "ACTIVE",
        "attributes": {
            **kc.get("attributes", {}),
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }
    })

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.activated", updated, "杀伤链已激活，资源状态同步启动")
    await sse_manager.push_overview_changed("planning_home", "KILL_CHAIN", rid, summary={"title": updated.get("title", ""), "state": "ACTIVE"})

    return ApiResponse(data={"kill_chain_id": kill_chain_id, "status": "ACTIVE", "message": "杀伤链已激活，资源状态同步启动"})


@router.post("/kill-chains/{kill_chain_id}/deactivate", response_model=ApiResponse)
async def deactivate_kill_chain(kill_chain_id: str):
    """静默杀伤链"""
    kc, rid = _get_kill_chain(kill_chain_id)
    updated = task_pool.patch(rid, {"state": "DEACTIVATED"})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.deactivated", updated, "杀伤链已静默，资源状态同步暂停")
    await sse_manager.push_overview_changed("planning_home", "KILL_CHAIN", rid, summary={"title": updated.get("title", ""), "state": "DEACTIVATED"})

    return ApiResponse(data={"kill_chain_id": kill_chain_id, "status": "DEACTIVATED", "message": "杀伤链已静默，资源状态同步暂停"})


@router.post("/decision/kill-chain-remapping", response_model=ApiResponse)
async def kill_chain_remapping(body: Dict[str, Any]):
    """杀伤链重映射"""
    kill_chain_id = body.get("kill_chain_id", "")
    kc, rid = _get_kill_chain(kill_chain_id)

    # mock 重映射：更新 network 节点状态
    stages = body.get("stages", [])
    resource_states = body.get("resource_states", {})

    # 更新 network 节点
    network = kc.get("network", {"nodes": [], "edges": []})
    for node in network.get("nodes", []):
        rid_node = node.get("resource_id", "")
        state = resource_states.get(rid_node, {})
        node["status"] = "ONLINE" if state.get("online") else "OFFLINE"
        node["status_color"] = "GREEN" if state.get("online") else "RED"
        if state.get("position"):
            node["position"] = state["position"]

    # 更新 stages 状态
    for stage in stages:
        for action in stage.get("actions", []):
            req_res = action.get("required_resources", [])
            # 检查所需资源是否在线
            all_online = True
            for rr in req_res:
                for node in network.get("nodes", []):
                    if node.get("name") == rr:
                        if node.get("status") == "OFFLINE":
                            all_online = False
                            break
            action["status"] = "READY" if all_online else "BLOCKED"
        stage["status"] = "IDLE" if all(
            a.get("status") == "READY" for a in stage.get("actions", [])
        ) else "BLOCKED"

    updated = task_pool.patch(rid, {"network": network})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain_mapping.completed", updated, "杀伤链重映射完成")

    return ApiResponse(data={
        "job_id": _new_id("remap"),
        "kill_chain_id": kill_chain_id,
        "status": "SUCCEEDED",
        "message": "杀伤链重映射完成",
    })


# ========== Task Pool 代理接口 ==========

@router.post("/task_pool/resources/query", response_model=ApiResponse)
async def task_pool_query(body: Dict[str, Any]):
    """查询 task_pool 资源"""
    results = task_pool.query(
        task_type=body.get("task_type"),
        state=body.get("state"),
        parent_resource_id=body.get("plan_id") or body.get("parent_resource_id"),
        keyword=body.get("keyword"),
        include_deleted=body.get("include_deleted", False),
        limit=body.get("limit", 50),
    )
    return ApiResponse(data={"items": results, "total": len(results)})


@router.get("/task_pool/resources/{resource_id}", response_model=ApiResponse)
async def task_pool_get(resource_id: str):
    """获取单个资源详情"""
    res = task_pool.get(resource_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    return ApiResponse(data=res)


@router.patch("/task_pool/resources/{resource_id}", response_model=ApiResponse)
async def task_pool_patch(resource_id: str, body: Dict[str, Any]):
    """增量更新资源"""
    payload = body.get("payload", body)
    updated = task_pool.patch(resource_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")

    # SSE 推送
    task_type = updated.get("task_type", "").lower()
    if task_type == "kill_chain":
        await sse_manager.push_kill_chain_detail(resource_id, "planning.detail.changed", updated, "资源已更新")

    return ApiResponse(data=updated)


@router.post("/task_pool/ingestion/import", response_model=ApiResponse)
async def task_pool_import(body: Dict[str, Any]):
    """批量导入资源"""
    resources = body.get("resources", [])
    ignore_errors = body.get("ignore_errors", False)
    result = task_pool.import_resources(resources, ignore_errors)

    # SSE 推送变更
    for rid in result.get("imported", []):
        res = task_pool.get(rid)
        if res:
            await sse_manager.push_overview_changed(
                "planning_home", res.get("task_type", ""), rid,
                summary={"title": res.get("title", ""), "state": res.get("state", "")},
                action="CREATE",
            )

    return ApiResponse(data=result)


@router.post("/task_pool/ingestion/commit", response_model=ApiResponse)
async def task_pool_commit(body: Dict[str, Any]):
    """提交 pending 数据"""
    cache_keys = body.get("cache_keys", [])
    result = task_pool.commit(cache_keys)
    return ApiResponse(data=result)


# ========== 资源池代理接口 ==========

@router.post("/resources/query", response_model=ApiResponse)
async def resources_query(body: Dict[str, Any]):
    """查询候选装备资源"""
    entity_kind = body.get("entity_kind", "")
    resource_ids = body.get("resource_ids", [])
    keyword = body.get("keyword", "")
    limit = body.get("limit", 20)

    all_resources = task_pool.all()
    results = []
    for res in all_resources.values():
        if res.get("task_type") != "EQUIPMENT":
            continue
        if entity_kind and res.get("entity_kind") != entity_kind:
            continue
        if resource_ids and res.get("resource_id") not in resource_ids:
            continue
        if keyword and keyword.lower() not in res.get("resource_name", "").lower():
            continue
        results.append(res)

    return ApiResponse(data={"items": results[:limit], "total": len(results)})


@router.get("/resources/{resource_id}/state", response_model=ApiResponse)
async def resource_state(resource_id: str):
    """获取装备实时状态"""
    res = task_pool.get(resource_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")

    state = {
        "resource_id": resource_id,
        "online": res.get("online_status") == "ONLINE",
        "position": res.get("capacity", {}).get("position") or {"latitude": 39.0, "longitude": 116.0, "z": 0},
        "address": f"http://{resource_id.replace(':', '-').replace('/', '')}:8850",
        "capability_snapshot": {"status": "NORMAL"},
    }
    return ApiResponse(data=state)


@router.post("/resources/batch/state", response_model=ApiResponse)
async def resources_batch_state(body: Dict[str, Any]):
    """批量获取装备状态"""
    resource_ids = body.get("resource_ids", [])
    states = {}
    for rid in resource_ids:
        res = task_pool.get(rid)
        if res:
            states[rid] = {
                "resource_id": rid,
                "online": res.get("online_status") == "ONLINE",
                "position": res.get("capacity", {}).get("position") or {"latitude": 39.0, "longitude": 116.0, "z": 0},
                "address": f"http://{rid.replace(':', '-').replace('/', '')}:8850",
                "capability_snapshot": {"status": "NORMAL"},
            }
        else:
            states[rid] = {
                "resource_id": rid,
                "online": False,
                "position": None,
                "address": None,
                "capability_snapshot": None,
            }
    return ApiResponse(data={"states": states})
