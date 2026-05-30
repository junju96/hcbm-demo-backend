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
    KillChainDispatchRequest,
    ResourceQuery, ApiResponse,
)
from app.services.task_pool import task_pool
from app.services.sse_manager import sse_manager
from app.services.data_server_client import (
    get_kill_chain as ds_get_kill_chain,
    query_kill_chains as ds_query_kill_chains,
    create_kill_chain as ds_create_kill_chain,
    patch_kill_chain as ds_patch_kill_chain,
    delete_kill_chain as ds_delete_kill_chain,
    to_frontend_killchain,
    to_frontend_killchain_list,
    validate_resource_state,
    VALID_RESOURCE_STATES,
    _http_post,
)
from app.services.sichen_client import call_plan_allocation

router = APIRouter()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _get_kill_chain(kill_chain_id: str):
    """获取杀伤链，优先从数据服务器查询（支持带前缀或不带前缀）"""
    rid = kill_chain_id if kill_chain_id.startswith("kill_chain:") else f"kill_chain:{kill_chain_id}"
    # 1. 优先从数据服务器获取
    kc = ds_get_kill_chain(rid)
    if kc:
        return kc, rid
    # 2. fallback 到本地内存
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
    """创建杀伤链 —— 调用数据服务器 import 接口（或 mock）"""
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
        "mapping_summary": {},
        "raw_entries": [],
        "assigned_entries": [],
        "network": {"nodes": [], "edges": []},
        "search_text": body.title + " " + body.description,
        "created_at": now,
        "updated_at": now,
        "attributes": {
            "created_from": "api",
            "target_display": target_display,
        },
    }

    # 调用数据服务器（或 mock fallback）
    result = ds_create_kill_chain(kill_chain)

    # SSE 推送
    await sse_manager.push_overview_changed(
        "planning_home", "KILL_CHAIN", rid,
        summary={"title": body.title, "state": "INIT"},
        action="CREATE",
    )

    return ApiResponse(data={"kill_chain_id": kc_id, "resource_id": rid, "status": "created", "ds_result": result})


@router.get("/kill-chains/{kill_chain_id}", response_model=ApiResponse)
async def get_kill_chain(kill_chain_id: str):
    """获取杀伤链详情 —— 调用数据服务器查询（或 mock fallback）"""
    rid = kill_chain_id if kill_chain_id.startswith("kill_chain:") else f"kill_chain:{kill_chain_id}"

    # 1. 调用数据服务器
    data = ds_get_kill_chain(rid)
    if data:
        return ApiResponse(data=to_frontend_killchain(data))

    # 2. fallback 到本地内存
    kc = task_pool.get(rid)
    if kc:
        return ApiResponse(data=kc)

    raise HTTPException(status_code=404, detail=f"KillChain not found: {kill_chain_id}")


@router.patch("/kill-chains/{kill_chain_id}", response_model=ApiResponse)
async def update_kill_chain(kill_chain_id: str, body: KillChainUpdate):
    """更新杀伤链 —— 调用数据服务器 PATCH（特有字段打包到 payload）"""
    rid = kill_chain_id if kill_chain_id.startswith("kill_chain:") else f"kill_chain:{kill_chain_id}"

    payload = body.model_dump(exclude_none=True)
    if not payload:
        kc = ds_get_kill_chain(rid) or task_pool.get(rid)
        return ApiResponse(data=to_frontend_killchain(kc) if kc else {})

    # 调用数据服务器（或 mock fallback）
    updated = ds_patch_kill_chain(rid, payload)
    if updated:
        # 同时更新本地缓存（保持兼容）
        task_pool.patch(rid, payload)

        # SSE 推送
        await sse_manager.push_kill_chain_detail(rid, "planning.detail.changed", updated, "杀伤链内容已更新")
        await sse_manager.push_overview_changed(
            "planning_home", "KILL_CHAIN", rid,
            summary={"title": updated.get("title", ""), "state": updated.get("state", "")},
        )

        return ApiResponse(data=to_frontend_killchain(updated))

    raise HTTPException(status_code=404, detail=f"KillChain not found: {kill_chain_id}")


@router.delete("/kill-chains/{kill_chain_id}", response_model=ApiResponse)
async def delete_kill_chain(kill_chain_id: str):
    """删除杀伤链 —— 调用数据服务器生命周期接口（或 mock）"""
    rid = kill_chain_id if kill_chain_id.startswith("kill_chain:") else f"kill_chain:{kill_chain_id}"

    success = ds_delete_kill_chain(rid)
    if success:
        task_pool.update_lifecycle(rid, "DELETED", "user_deleted")
        await sse_manager.push_overview_changed(
            "planning_home", "KILL_CHAIN", rid,
            summary={"title": "", "state": "DELETED"},
            action="DELETE",
        )
        return ApiResponse(data={"kill_chain_id": kill_chain_id, "result": "success"})

    raise HTTPException(status_code=404, detail=f"KillChain not found: {kill_chain_id}")


@router.post("/kill-chains/{kill_chain_id}/forward", response_model=ApiResponse)
async def forward_kill_chain(kill_chain_id: str, body: Dict[str, str]):
    """转发杀伤链"""
    kc, rid = _get_kill_chain(kill_chain_id)
    target = body.get("target", "")
    return ApiResponse(data={"kill_chain_id": kill_chain_id, "result": "success", "target": target})


# ========== Entries 管理 ==========

@router.post("/kill-chains/{kill_chain_id}/entries", response_model=ApiResponse)
async def add_entry(kill_chain_id: str, body: KillChainEntryCreate):
    """增加杀伤链条目 —— 更新数据服务器 raw_entries"""
    rid = kill_chain_id if kill_chain_id.startswith("kill_chain:") else f"kill_chain:{kill_chain_id}"

    # 从数据服务器获取最新数据
    kc = ds_get_kill_chain(rid) or task_pool.get(rid)
    if not kc:
        raise HTTPException(status_code=404, detail=f"KillChain not found: {kill_chain_id}")

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

    # 调用数据服务器 PATCH（特有字段打包到 payload）
    updated = ds_patch_kill_chain(rid, {"raw_entries": raw_entries})
    # 同时更新本地缓存
    task_pool.patch(rid, {"raw_entries": raw_entries})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.entries_changed", updated or kc, "杀伤链条目已增加")

    return ApiResponse(data={"entry_id": entry_id, "kill_chain_id": kill_chain_id})


@router.delete("/kill-chains/{kill_chain_id}/entries/{entry_id}", response_model=ApiResponse)
async def delete_entry(kill_chain_id: str, entry_id: str):
    """删除杀伤链条目 —— 更新数据服务器"""
    rid = kill_chain_id if kill_chain_id.startswith("kill_chain:") else f"kill_chain:{kill_chain_id}"

    kc = ds_get_kill_chain(rid) or task_pool.get(rid)
    if not kc:
        raise HTTPException(status_code=404, detail=f"KillChain not found: {kill_chain_id}")

    raw_entries = [e for e in kc.get("raw_entries", []) if e.get("entry_id") != entry_id]
    assigned_entries = [e for e in kc.get("assigned_entries", []) if e.get("entry_id") != entry_id]

    # 调用数据服务器 PATCH
    updated = ds_patch_kill_chain(rid, {"raw_entries": raw_entries, "assigned_entries": assigned_entries})
    task_pool.patch(rid, {"raw_entries": raw_entries, "assigned_entries": assigned_entries})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.entries_changed", updated or kc, "杀伤链条目已删除")

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
        "entry_id": entry_id,
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

    # 替换已有同 entry_id 的分配记录，而非追加
    prev_assigned = kc.get("assigned_entries", [])
    assigned_entries = [e for e in prev_assigned if e.get("entry_id") != entry_id] + [assigned_entry]

    # 调用数据服务器 PATCH
    updated = ds_patch_kill_chain(rid, {"assigned_entries": assigned_entries})
    task_pool.patch(rid, {"assigned_entries": assigned_entries})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.resource_allocated", updated or kc, "自动分配完成")

    return ApiResponse(data={
        "job_id": _new_id("auto-alloc"),
        "kill_chain_id": kill_chain_id,
        "entry_id": entry_id,
        "selected_executor": chosen["executor_id"],
        "status": "SUCCEEDED",
    })


@router.post("/kill-chains/{kill_chain_id}/batch-auto-allocate", response_model=ApiResponse)
async def batch_auto_allocate(kill_chain_id: str, body: Dict[str, Any] = None):
    """
    批量自动分配 — 调用 sichen 火力规划小模型。
    body 可传 {"entry_ids": [...]}，为空则处理所有未分配条目。
    """
    kc, rid = _get_kill_chain(kill_chain_id)
    body = body or {}
    specified_ids = body.get("entry_ids", [])

    raw_entries = kc.get("raw_entries", [])
    if specified_ids:
        target_entries = [e for e in raw_entries if e.get("entry_id") in specified_ids and not e.get("selected_executor")]
    else:
        target_entries = [e for e in raw_entries if not e.get("selected_executor")]

    if not target_entries:
        return ApiResponse(code=200, message="没有需要自动分配的条目", data={"allocations": []})

    # ---------- 1. 收集装备和目标 ----------
    resource_ids = kc.get("resource_ids", [])
    target_ids = kc.get("target_ids", [])

    # 装备名称 -> ID 映射
    name_to_resource: Dict[str, str] = {}
    vehicles: List[Dict[str, Any]] = []
    for res_id in resource_ids:
        res = task_pool.get(res_id)
        if not res:
            continue
        name = res.get("resource_name") or res_id.replace("equipment:", "")
        name_to_resource[name] = res_id
        vehicles.append({
            "vehicle_id": name,
            "platform_type": "light",
            "longitude": res.get("location", {}).get("longitude", 118.2),
            "latitude": res.get("location", {}).get("latitude", 39.86),
            "ammunition": [{"ammo_type": "FTK", "ammo_count": 10}],
            "faults": [],
        })

    # target 短 ID -> 完整 ID 映射
    short_to_target: Dict[str, str] = {}
    targets: List[Dict[str, Any]] = []
    for tid in target_ids:
        t = task_pool.get(tid)
        short_id = tid.replace("target:", "")
        short_to_target[short_id] = tid
        loc = t.get("location", {}) if t else {}
        targets.append({
            "target_id": short_id,
            "name": t.get("target_name", short_id) if t else short_id,
            "type": "239",
            "center_position": {
                "lat": loc.get("latitude", 39.86),
                "lon": loc.get("longitude", 118.2),
            },
            "object_level": "特级",
            "threat": 100,
            "object_requirement_result": "彻底摧毁",
        })

    # ---------- 2. 调用 sichen ----------
    sichen_result = call_plan_allocation(vehicles, targets)
    if not sichen_result:
        return ApiResponse(code=503, message="sichen 火力规划服务调用失败", data=None)

    vehicle_missions = sichen_result.get("vehicle_missions", {})

    # ---------- 3. 解析分配结果并构建 assigned_entries ----------
    assigned_entries = list(kc.get("assigned_entries", []))
    allocations = []

    for v_name, tasks in vehicle_missions.items():
        res_id = name_to_resource.get(v_name)
        if not res_id:
            continue
        for task in tasks:
            target_short = task.get("target_id", "")
            full_tid = short_to_target.get(target_short)
            if not full_tid:
                continue
            # 找一个包含该目标且未分配的 entry（按 operation + target_ids 判断）
            def _already_allocated(entry):
                for a in assigned_entries:
                    if a.get("operation") == entry["operation"] and set(a.get("target_ids", [])) == set(entry.get("target_ids", [])):
                        return True
                return False

            match_entry = next(
                (e for e in target_entries
                 if full_tid in e.get("target_ids", [])
                 and not _already_allocated(e)),
                None
            )
            if not match_entry:
                continue

            assigned = {
                "entry_id": match_entry["entry_id"],
                "phase": "ASSIGNED",
                "entry_seq": match_entry["entry_seq"],
                "target_ids": match_entry["target_ids"],
                "operation": match_entry["operation"],
                "executor_options": [{
                    "executor_id": res_id,
                    "allocation_count": 1,
                    "locked": True,
                    "note": f"sichen自动分配: {v_name} -> {target_short} (毁伤概率 {task.get('damage_probability', 0)})",
                }],
                "selected_executor": res_id,
                "locked": True,
                "is_valid": True,
                "notes": f"火力规划分配: 武器={task.get('weapon','FTK')}, 弹药={task.get('planned_ammo',1)}",
            }
            # 替换已有同 entry_id 的分配记录
            assigned_entries = [e for e in assigned_entries if e.get("entry_id") != match_entry["entry_id"]] + [assigned]
            allocations.append({
                "entry_id": match_entry["entry_id"],
                "selected_executor": res_id,
                "vehicle": v_name,
                "target": target_short,
                "weapon": task.get("weapon"),
                "damage_probability": task.get("damage_probability"),
            })

    # ---------- 4. 更新存储 ----------
    if allocations:
        ds_patch_kill_chain(rid, {"assigned_entries": assigned_entries})
        task_pool.patch(rid, {"assigned_entries": assigned_entries})
        await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.resource_allocated", task_pool.get(rid) or kc, "批量自动分配完成")

    return ApiResponse(data={
        "allocations": allocations,
        "total": len(allocations),
        "sichen_report": sichen_result.get("report", {}),
    })


@router.post("/kill-chains/{kill_chain_id}/entries/{entry_id}/allocate", response_model=ApiResponse)
async def manual_allocate(kill_chain_id: str, entry_id: str, body: ResourceAllocate):
    """人工分配资源"""
    kc, rid = _get_kill_chain(kill_chain_id)

    # 获取资源名称
    res = task_pool.get(body.selected_executor)
    resource_name = res.get("resource_name", body.selected_executor) if res else body.selected_executor

    assigned_entry = {
        "entry_id": entry_id,
        "phase": "ASSIGNED",
        "entry_seq": 0,
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

    # 替换已有同 entry_id 的分配记录，而非追加
    prev_assigned = kc.get("assigned_entries", [])
    assigned_entries = [e for e in prev_assigned if e.get("entry_id") != entry_id] + [assigned_entry]

    # 调用数据服务器 PATCH
    updated = ds_patch_kill_chain(rid, {"assigned_entries": assigned_entries})
    task_pool.patch(rid, {"assigned_entries": assigned_entries})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.resource_allocated", updated or kc, "人工分配完成")

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

    # 过滤已分配条目（未传 selected_entry_ids 时默认使用全部已分配条目）
    assigned = kc.get("assigned_entries", [])
    entry_ids = body.selected_entry_ids or []
    if entry_ids:
        selected = [e for e in assigned if e.get("entry_id") in entry_ids]
    else:
        selected = assigned

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
        "state": "DRAFT",
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

    # 0. 校验 plan state 合法性（避免数据服务器 500）
    is_valid, err_msg = validate_resource_state(plan)
    if not is_valid:
        return ApiResponse(code=400, message=f"生成的方案 state 不合法: {err_msg}", data=None)

    # 1. 将生成的方案通过数据服务器 import 接口存入
    import_result = _http_post(
        "/api/v1/task_pool/ingestion/import",
        {"resources": [plan], "return_data_type": "typed", "ignore_errors": True},
    )
    # 无论数据服务器是否成功，都写入本地内存（数据服务器 PLAN 查询 500 时可作为 fallback）
    task_pool.set(plan_rid, plan)

    # 2. 删除原杀伤链（调用数据服务器 lifecycle 接口）
    delete_ok = ds_delete_kill_chain(rid)
    if delete_ok:
        task_pool.update_lifecycle(rid, "DELETED", "mapped_to_plan")

    # SSE 推送
    await sse_manager.push_overview_changed(
        "planning_home", "PLAN", plan_rid,
        summary={"title": plan["title"], "state": plan["state"]},
        action="CREATE",
    )
    if delete_ok:
        await sse_manager.push_overview_changed(
            "planning_home", "KILL_CHAIN", rid,
            summary={"title": kc.get("title", ""), "state": "DELETED"},
            action="DELETE",
        )

    return ApiResponse(data={
        "plan_id": plan_rid,
        "kill_chain_id": kill_chain_id,
        "status": "SUCCEEDED",
        "message": "方案已生成并映射到数据服务器",
        "imported": import_result is not None,
        "deleted": delete_ok,
    })


# ========== 激活 / 静默 / 重映射 ==========

@router.post("/kill-chains/{kill_chain_id}/activate", response_model=ApiResponse)
async def activate_kill_chain(kill_chain_id: str):
    """激活杀伤链"""
    kc, rid = _get_kill_chain(kill_chain_id)
    updated = ds_patch_kill_chain(rid, {
        "state": "ACTIVE",
        "attributes": {
            **kc.get("attributes", {}),
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }
    })
    task_pool.patch(rid, {
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
    updated = ds_patch_kill_chain(rid, {"state": "DEACTIVATED"})
    task_pool.patch(rid, {"state": "DEACTIVATED"})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.deactivated", updated, "杀伤链已静默，资源状态同步暂停")
    await sse_manager.push_overview_changed("planning_home", "KILL_CHAIN", rid, summary={"title": updated.get("title", ""), "state": "DEACTIVATED"})

    return ApiResponse(data={"kill_chain_id": kill_chain_id, "status": "DEACTIVATED", "message": "杀伤链已静默，资源状态同步暂停"})


@router.post("/kill-chains/{kill_chain_id}/dispatch", response_model=ApiResponse)
async def dispatch_kill_chain(kill_chain_id: str, body: KillChainDispatchRequest):
    """下发杀伤链分配方案：接收前端本地编辑后的分配信息，更新 assigned_entries 并存入数据服务器"""
    kc, rid = _get_kill_chain(kill_chain_id)

    raw_entries = kc.get("raw_entries", [])
    prev_assigned = kc.get("assigned_entries", [])
    modified_ids = set()
    new_assigned = []

    for item in body.entries:
        entry_id = item.entry_id
        raw_entry = next((e for e in raw_entries if e.get("entry_id") == entry_id), None)
        if not raw_entry:
            continue

        selected_executor = item.selected_executor
        executor_assignments = item.executor_assignments or []

        if not selected_executor:
            # 空分配：跳过（表示取消分配）
            modified_ids.add(entry_id)
            continue

        # 构建 assigned_entry
        assigned_entry = {
            "entry_id": entry_id,
            "phase": "ASSIGNED",
            "entry_seq": raw_entry.get("entry_seq", 0),
            "target_ids": raw_entry.get("target_ids", []),
            "operation": raw_entry.get("operation", ""),
            "executor_options": [{
                "executor_id": selected_executor,
                "allocation_count": 1,
                "locked": True,
                "note": f"人工分配选中{selected_executor}",
            }],
            "selected_executor": selected_executor,
            "locked": True,
            "is_valid": True,
            "notes": "人工分配下发",
        }
        new_assigned.append(assigned_entry)
        modified_ids.add(entry_id)

    # 保留未被修改的旧 assigned_entries，加上新的
    final_assigned = [e for e in prev_assigned if e.get("entry_id") not in modified_ids] + new_assigned

    ds_patch_kill_chain(rid, {"assigned_entries": final_assigned})
    task_pool.patch(rid, {"assigned_entries": final_assigned})

    await sse_manager.push_kill_chain_detail(rid, "planning.kill_chain.dispatched", task_pool.get(rid) or kc, "杀伤链分配方案已下发")

    # TODO: 发送给无人车

    return ApiResponse(data={
        "kill_chain_id": kill_chain_id,
        "dispatched": len(new_assigned),
        "status": "DISPATCHED",
        "message": "杀伤链分配方案已下发",
    })


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

    updated = ds_patch_kill_chain(rid, {"network": network})
    task_pool.patch(rid, {"network": network})

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
    """查询 task_pool 资源 —— 优先数据服务器，空结果 fallback 本地内存"""
    task_type = body.get("task_type")
    limit = body.get("limit", 50)

    # KILL_CHAIN 类型：只从数据服务器查询，不再合并本地 mock
    if task_type == "KILL_CHAIN":
        ds_items = ds_query_kill_chains(limit=limit) or []
        return ApiResponse(data={"items": to_frontend_killchain_list(ds_items), "total": len(ds_items)})

    # PLAN 类型：从数据服务器查询（不再使用本地 mock）
    if task_type == "PLAN":
        ds_data = _http_get("/api/v1/task_pool/resources/by_type/PLAN", silent=True)
        items = []
        if ds_data is not None:
            if isinstance(ds_data, list):
                items = ds_data[:limit]
            elif isinstance(ds_data, dict):
                items = (ds_data.get("items") or ds_data.get("data") or [])[:limit]
        adapted = []
        for item in items:
            raw = item.get("raw_payload", {}) or item if isinstance(item, dict) else {}
            adapted.append({
                "resource_id": item.get("resource_id", ""),
                "resource_name": raw.get("title") or item.get("title", ""),
                "task_type": "PLAN",
                "state": raw.get("state") or item.get("state", "DRAFT"),
                "resource_detail": item,
            })
        return ApiResponse(data={"items": adapted, "total": len(adapted)})

    # 其他类型：使用本地内存
    results = task_pool.query(
        task_type=task_type,
        state=body.get("state"),
        parent_resource_id=body.get("plan_id") or body.get("parent_resource_id"),
        keyword=body.get("keyword"),
        include_deleted=body.get("include_deleted", False),
        limit=limit,
    )
    return ApiResponse(data={"items": results, "total": len(results)})


@router.get("/task_pool/resources/{resource_id}", response_model=ApiResponse)
async def task_pool_get(resource_id: str):
    """获取单个资源详情 — KILL_CHAIN 优先从数据服务器查询"""
    # KILL_CHAIN 类型优先从数据服务器获取
    if resource_id.startswith("kill_chain:") or "kill_chain" in resource_id:
        res = ds_get_kill_chain(resource_id)
        if res:
            return ApiResponse(data=res)
    res = task_pool.get(resource_id)
    if not res:
        raise HTTPException(status_code=404, detail=f"Resource not found: {resource_id}")
    return ApiResponse(data=res)


@router.patch("/task_pool/resources/{resource_id}", response_model=ApiResponse)
async def task_pool_patch(resource_id: str, body: Dict[str, Any]):
    """增量更新资源 — KILL_CHAIN 类型转发到数据服务器"""
    payload = body.get("payload", body)
    # 判断是否是 KILL_CHAIN
    existing = task_pool.get(resource_id) or {}
    is_kill_chain = existing.get("task_type") == "KILL_CHAIN" or resource_id.startswith("kill_chain:")

    if is_kill_chain:
        updated = ds_patch_kill_chain(resource_id, payload)
        if updated:
            task_pool.patch(resource_id, payload)
            await sse_manager.push_kill_chain_detail(resource_id, "planning.detail.changed", updated, "资源已更新")
            return ApiResponse(data=updated)

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
