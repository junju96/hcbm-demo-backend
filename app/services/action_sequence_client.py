"""
行动序列数据服务客户端
职责：
  1. 从数据服务器获取 PLAN / STAGE / ACTION 数据
  2. 将 plan.team_actions 转换为按车辆(vid)组织的行动序列
  3. 维护行动序列的运行状态（内存）
  4. plan → MissionService mission_data 格式转换

与杀伤链的区分：
  - 杀伤链: data_server_client.py 处理 KILL_CHAIN 类型
  - 行动序列: action_sequence_client.py 处理 PLAN / STAGE / ACTION / CAR_ACTIONS 类型
"""

import copy
import hashlib
import re
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone

from app.services.data_server_client import (
    _http_get, _http_post, _http_patch,
    _http_get_operator, _http_post_operator, _http_patch_operator,
    _http_get_resource_pool,
)
from app.services.task_pool import task_pool
from app.services import zenoh_client


def _infer_resource_type_from_vid(vid: str) -> str:
    """从 equipment vid 推断 resource_type，用于数据服务器 team_equipments 为空时的兜底。"""
    if "fire-support" in vid:
        return "Fire-Support-UGV"
    if "recon-strike" in vid:
        return "Recon-Strike-UGV"
    if "patrol" in vid:
        return "Patrol-UGV"
    if "electronic" in vid:
        return "Electronic-UGV"
    if "air-ground" in vid:
        return "Air-Ground-UAV"
    return ""


def _build_car_actions_from_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    将 plan.stages[].team_actions 转换为按车辆(vid)组织的行动序列列表。
    兼容三种数据结构：
      - 数据服务器标准 /simple: team_actions 为 list[{"team_id": "...", "car_actions": [...]}]
      - 旧真实服务器: team_actions 为 list[{"team_id": "...", "team_actions": [...]}]
      - 旧 Mock 数据: team_actions 为 dict{"team_id": [...]}
    """
    plan_id = plan.get("plan_id", "")
    stages = plan.get("stages", [])
    results: List[Dict[str, Any]] = []

    for stage in stages:
        stage_id = stage.get("stage_id", "")
        stage_seq = stage.get("stage_seq", 0)
        stage_title = stage.get("title", "")
        team_actions = stage.get("team_actions", {})

        # 统一为 list[(team_id, vehicles)] 格式
        team_vehicle_pairs: List[tuple] = []
        if isinstance(team_actions, dict):
            for team_id, vehicles in team_actions.items():
                team_vehicle_pairs.append((team_id, vehicles))
        elif isinstance(team_actions, list):
            for ta in team_actions:
                team_id = ta.get("team_id", "")
                # 标准 /simple 接口使用 car_actions，旧接口使用 team_actions
                car_actions = ta.get("car_actions", [])
                if car_actions:
                    team_vehicle_pairs.append((team_id, car_actions))
                else:
                    vehicles = ta.get("team_actions", [])
                    if vehicles:
                        team_vehicle_pairs.append((team_id, vehicles))
                    # 防御性兼容：数组元素直接是 vehicle 对象（vid + actions）
                    elif ta.get("vid") and ta.get("actions") is not None:
                        team_vehicle_pairs.append((team_id, [ta]))

        for team_id, vehicles in team_vehicle_pairs:
            if not isinstance(vehicles, list):
                continue
            for vehicle in vehicles:
                if not isinstance(vehicle, dict):
                    continue
                vid = vehicle.get("vid", "")
                actions = vehicle.get("actions", [])
                ca_id = f"ca:{plan_id}:{stage_id}:{vid}"
                results.append({
                    "car_actions_id": ca_id,
                    "vid": vid,
                    "plan_id": plan_id,
                    "stage_id": stage_id,
                    "stage_seq": stage_seq,
                    "stage_title": stage_title,
                    "team_id": team_id,
                    "actions": copy.deepcopy(actions),
                    "state": vehicle.get("state") or "SCHEDULED",
                    "action_type": vehicle.get("action_type", ""),
                })

    # 按 stage_seq -> vid 排序
    results.sort(key=lambda x: (x["stage_seq"], x["vid"]))
    return results


def _normalize_plan_field_names(obj: Any) -> Any:
    """
    将数据服务器返回的扁平字段名归一化为本地 mock 使用的字段名。
    例如 plan_title -> title, action_name -> name, team_equipments -> vehicles。
    """
    if isinstance(obj, list):
        return [_normalize_plan_field_names(item) for item in obj]
    if not isinstance(obj, dict):
        return obj

    # 字段名映射：数据服务器字段 -> 本地字段
    key_map = {
        "plan_title": "title",
        "plan_description": "description",
        "stage_title": "title",
        "stage_description": "description",
        "team_name": "name",
        "team_description": "description",
        "team_equipments": "vehicles",
        "action_name": "name",
        "action_description": "description",
    }

    normalized: Dict[str, Any] = {}
    for k, v in obj.items():
        new_key = key_map.get(k, k)
        normalized[new_key] = _normalize_plan_field_names(v)
    return normalized


def query_plans(limit: int = 20) -> List[Dict[str, Any]]:
    """查询行动方案列表 — 调用数据服务器 POST /resources/query（静默模式，不打印日志）。
    数据服务器不可达或为空时，回退到本地 task_pool；本地 fake 调测方案合并到列表最前（调试用）。"""
    data = _http_post(
        "/api/v1/task_pool/resources/query",
        {"task_type": "PLAN", "limit": limit},
        silent=True,
    )
    items = []
    if data is not None and isinstance(data, list):
        items = data[:limit]
    elif data is not None and isinstance(data, dict):
        # /retrieval/query 返回 { items: [...] }
        items = (data.get("items") or data.get("data") or [])[:limit]

    # 合并本地 fake 调测方案（FAKE_ACTION_SEQUENCE_LOCAL_001），方便本地调试。
    # TODO: 后续删除本地假数据逻辑时，移除此段合并代码。
    local_items = task_pool.query(task_type="PLAN", limit=limit)
    FAKE_PLAN_ID = "FAKE_ACTION_SEQUENCE_LOCAL_001"
    if not items:
        print("[AS-DEBUG] query_plans fallback to local task_pool")
        items = local_items
    else:
        server_ids = {
            (item.get("plan_id") or item.get("resource_id", "").replace("plan:", ""))
            for item in items
        }
        for local_item in local_items:
            local_id = local_item.get("plan_id") or local_item.get("resource_id", "").replace("plan:", "")
            # 仅合并本地 fake 调测方案，不要把真实 plan 的本地缓存插入列表
            if local_id == FAKE_PLAN_ID and local_id not in server_ids:
                items.insert(0, local_item)

    result = []
    for idx, item in enumerate(items):
        item = _normalize_plan_field_names(item)
        tactic = item.get("tactic") or {}
        if not isinstance(tactic, dict):
            tactic = {}
        title = (
            item.get("title")
            or tactic.get("title")
            or item.get("plan_id")
            or ""
        )
        state = item.get("state") or "DRAFT"
        stages = item.get("stages") or []
        if idx == 0:
            print(f"[AS-DEBUG] query_plans first item: resource_id={item.get('resource_id')}, stages_count={len(stages) if isinstance(stages, list) else 'N/A'}")
        result.append({
            "plan_id": item.get("plan_id") or item.get("resource_id", "").replace("plan:", ""),
            "resource_id": item.get("resource_id", ""),
            "title": title,
            "description": item.get("description") or "",
            "state": state,
            "teams_count": len(item.get("teams") or []),
            "stages_count": len(stages),
        })
    return result


def get_plan_detail(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    获取方案详情，并转换为前端行动序列需要的格式（静默模式，不打印日志）。
    数据服务器不可达时回退到本地 task_pool；本地也没有时返回 None。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    data = _http_get(f"/api/v1/task_pool/resources/simple/{rid}", silent=True)
    if data is not None and isinstance(data, dict):
        # 数据服务端 /simple 接口返回的是业务字段（已做字段投影）
        plan = _normalize_plan_field_names(data)

        # 比较本地和远程 plan 的 actions 数量，优先使用 actions 更完整的版本，
        # 避免数据服务器 /simple 接口投影丢失 team_actions 后覆盖本地完整数据。
        def _count_actions(p):
            if not p or not isinstance(p, dict):
                return 0
            count = 0
            for stage in p.get("stages", []) or []:
                team_actions = stage.get("team_actions", {})
                if isinstance(team_actions, dict):
                    for vlist in team_actions.values():
                        if isinstance(vlist, list):
                            for v in vlist:
                                if isinstance(v, dict):
                                    count += len(v.get("actions") or [])
                elif isinstance(team_actions, list):
                    for ta in team_actions:
                        if not isinstance(ta, dict):
                            continue
                        for v in ta.get("car_actions", []) or []:
                            if isinstance(v, dict):
                                count += len(v.get("actions") or [])
                        for v in ta.get("team_actions", []) or []:
                            if isinstance(v, dict):
                                count += len(v.get("actions") or [])
            return count

        local_plan = task_pool.get(rid)
        local_actions = _count_actions(local_plan)
        remote_actions = _count_actions(plan)
        if local_plan and local_actions > remote_actions:
            print(f"[AS-DEBUG] get_plan_detail use local task_pool (actions={local_actions} > remote={remote_actions}), plan_id={plan_id}")
            plan = local_plan
        else:
            print(f"[AS-DEBUG] get_plan_detail use remote (remote_actions={remote_actions} >= local={local_actions}), plan_id={plan_id}")

        # 同步缓存到本地 task_pool，方便后续 PATCH 更新
        task_pool.set(rid, plan)
    else:
        # 服务器不可达时 fallback 到本地 task_pool（支持 fake 调测数据）
        print(f"[AS-DEBUG] get_plan_detail fallback to local task_pool, plan_id={plan_id}")
        plan = task_pool.get(rid)

    if plan is None:
        print(f"[AS-DEBUG] plan={plan_id} not found in data_server or local task_pool")
        return None

    car_actions = _build_car_actions_from_plan(plan)
    result = _to_frontend_plan(plan, car_actions)
    # 根据数据服务端中的 action 状态推断并初始化运行时状态（避免前后端不一致）
    action_runtime.init_state_from_plan(plan_id, result)
    # 调试：打印第一个 vehicle 的第一个 action 的字段
    vs = result.get("vehicle_summary", [])
    if vs:
        first_actions = (vs[0].get("stages") or [{}])[0].get("actions", [])
        if first_actions:
            print(f"[AS-DEBUG] plan={plan_id} first_action_keys={list(first_actions[0].keys())} action_type={first_actions[0].get('action_type')}")
        else:
            print(f"[AS-DEBUG] plan={plan_id} no actions in first vehicle stage")
    return result


def _infer_vehicle_type_from_action_type(action_type: str) -> str:
    """根据 action_type 推断车辆类型，用于 plan.teams 中缺少 resource_type 时的兜底。

    注意：底盘类元任务（Auto-Move 等）对所有车型通用，不能用于推断车型，
    因此这里只根据各车型特有的载荷任务进行推断。
    """
    t = (action_type or "").strip().lower()
    if not t:
        return ""
    # 火力车
    if t in {"lens-recon", "search-and-shoot", "recon-strike", "rocket-launch", "loitering-munition-launch", "7.62mm-gun-shot", "gun-shot"}:
        return "Fire-Support-UGV"
    # 侦打车
    if t in {"40mm-gun-launch", "at-missile-launch", "laser-illumination"}:
        return "Recon-Strike-UGV"
    # 巡逻车
    if t in {"sound-expel", "acoustic-deterrence", "light-expel", "light-deterrence"}:
        return "Patrol-UGV"
    # 电磁车
    if t in {"em-recon", "electronic-recon", "em-interference", "electronic-jamming", "payload-silent"}:
        return "Electronic-UGV"
    # 空地车
    if t in {"air-recon", "air_recon", "ag_air_recon"}:
        return "Air-Ground-UAV"
    return ""


def _to_frontend_plan(plan: Dict[str, Any], car_actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """转换为前端需要的 Plan + ActionSequence 格式"""
    # 先建立 vid -> resource_type 映射（从 plan.teams 查找）
    team_type_map: Dict[str, str] = {}
    for team in plan.get("teams", []):
        if isinstance(team, dict):
            vehicles = team.get("vehicles", [])
            for v in vehicles:
                if isinstance(v, dict) and v.get("vid"):
                    team_type_map[v["vid"]] = v.get("resource_type", "")
            if team.get("vid"):
                team_type_map[team["vid"]] = team.get("resource_type", "")

    # 车辆汇总：按 vid 聚合所有阶段中的行动
    vehicle_map: Dict[str, Dict[str, Any]] = {}
    for ca in car_actions:
        vid = ca["vid"]
        if vid not in vehicle_map:
            vehicle_map[vid] = {
                "vid": vid,
                "resource_type": team_type_map.get(vid) or _infer_resource_type_from_vid(vid),
                "total_actions": 0,
                "current_state": "READY",
                "stages": [],
            }
        actions = ca.get("actions", [])
        action_type = ca.get("action_type", "")
        # 把 car_actions 的 action_type 注入到每个 action 中
        if action_type:
            actions = [dict(a, action_type=action_type) for a in actions]

        # 同一个 stage_id 已存在则合并 actions，避免重复 stage
        existing_stage = next(
            (s for s in vehicle_map[vid]["stages"] if s["stage_id"] == ca["stage_id"]), None
        )
        if existing_stage:
            seen_ids = {a.get("action_id") or a.get("action_seq") for a in existing_stage["actions"]}
            for a in actions:
                aid = a.get("action_id") or a.get("action_seq")
                if aid not in seen_ids:
                    seen_ids.add(aid)
                    existing_stage["actions"].append(a)
            # 重新计算 total_actions
            vehicle_map[vid]["total_actions"] = sum(len(s["actions"]) for s in vehicle_map[vid]["stages"])
        else:
            vehicle_map[vid]["total_actions"] += len(actions)
            vehicle_map[vid]["stages"].append({
                "stage_id": ca["stage_id"],
                "stage_title": ca["stage_title"],
                "stage_seq": ca["stage_seq"],
                "actions": actions,
                "state": ca.get("state", "READY"),
            })

    # 兜底：对仍无法识别车型的车辆，根据其 action_type 推断 resource_type
    for vdata in vehicle_map.values():
        if vdata["resource_type"]:
            continue
        for stage in vdata.get("stages", []):
            for action in stage.get("actions", []):
                inferred = _infer_vehicle_type_from_action_type(action.get("action_type", ""))
                if inferred:
                    vdata["resource_type"] = inferred
                    break
            if vdata["resource_type"]:
                break

    # title fallback：plan.title -> tactic.title -> plan_id
    tactic = plan.get("tactic") or {}
    if not isinstance(tactic, dict):
        tactic = {}
    title = (
        plan.get("title")
        or tactic.get("title")
        or plan.get("plan_id", "")
    )
    return {
        "plan_id": plan.get("plan_id", ""),
        "resource_id": plan.get("resource_id", ""),
        "title": title,
        "description": plan.get("description", ""),
        "state": plan.get("state") or "DRAFT",
        "stages": plan.get("stages", []),
        "teams": plan.get("teams", []),
        "targets": plan.get("targets", []),
        "car_actions": car_actions,
        "vehicle_summary": list(vehicle_map.values()),
    }


def update_action_param(plan_id: str, action_id: str, param: Dict[str, Any]) -> bool:
    """
    更新 plan 中指定 action 的 param。

    策略：
      1. 尝试 PATCH 数据服务器（如果数据服务端支持 action param 更新）。
      2. 同时同步更新本地 task_pool 中的缓存数据，保证前端编辑结果可立即生效。
         本地缓存可用于数据服务器不可达或 /simple 接口未返回完整 actions 时的 fallback。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    # 1. 最佳努力 PATCH 数据服务器
    patch_ok = False
    try:
        resp = _http_patch(
            f"/api/v1/task_pool/resources/{rid}/actions/{action_id}",
            {"action_id": action_id, "param": param},
            silent=True,
        )
        patch_ok = resp is not None
    except Exception:
        pass

    # 2. 确保本地 task_pool 中有该 plan 的缓存
    plan = task_pool.get(rid)
    if plan is None:
        data = _http_get(f"/api/v1/task_pool/resources/simple/{rid}", silent=True)
        if data is not None and isinstance(data, dict):
            plan = _normalize_plan_field_names(data)
            task_pool.set(rid, plan)

    if plan is None:
        # 本地没有缓存且服务器不可达，无法更新
        return patch_ok

    # 3. 在 plan.stages[].team_actions 中查找并更新 action.param
    updated = False
    for stage in plan.get("stages", []):
        team_actions = stage.get("team_actions", {})
        vehicles: List[Dict[str, Any]] = []
        if isinstance(team_actions, dict):
            for vlist in team_actions.values():
                if isinstance(vlist, list):
                    vehicles.extend(vlist)
        elif isinstance(team_actions, list):
            for ta in team_actions:
                # 标准格式：{ team_id, car_actions: [...] }
                vehicles.extend(ta.get("car_actions", []))
                # 兼容旧格式：{ team_id, team_actions: [...] }
                if not ta.get("car_actions"):
                    vehicles.extend(ta.get("team_actions", []))

        for vehicle in vehicles:
            for action in vehicle.get("actions", []):
                if action.get("action_id") == action_id:
                    action["param"] = copy.deepcopy(param)
                    updated = True
                    break
            if updated:
                break
        if updated:
            break

    if updated:
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        # 标记本地已被修改，避免后续 get_plan_detail 被数据服务器旧缓存覆盖
        plan["local_dirty"] = True
        task_pool.set(rid, plan)
        print(f"[AS-DEBUG] updated action param locally: plan_id={plan_id} action_id={action_id}")
    else:
        print(f"[AS-DEBUG] action not found locally: plan_id={plan_id} action_id={action_id} stages_team_actions_type={type(plan.get('stages',[{}])[0].get('team_actions')).__name__ if plan.get('stages') else 'no_stages'}")

    return updated or patch_ok


# ========== 行动序列运行时状态管理（内存） ==========

class ActionSequenceRuntime:
    """
    维护每个 plan 的行动序列运行时状态。
    状态：SCHEDULED / ACTIVE / PAUSED / DONE / DELETED
    """

    VALID_STATES = {"SCHEDULED", "ACTIVE", "PAUSED", "DONE", "DELETED"}
    TRANSITIONS = {
        "SCHEDULED": {"ACTIVE"},
        "ACTIVE": {"PAUSED", "DONE", "SCHEDULED"},
        "PAUSED": {"ACTIVE", "SCHEDULED", "DONE"},
        "DONE": {"SCHEDULED"},
        "DELETED": set(),
    }

    def __init__(self):
        # plan_id -> {"state": str, "started_at": str|None, "paused_at": str|None}
        self._states: Dict[str, Dict[str, Any]] = {}

    def _ensure(self, plan_id: str):
        if plan_id not in self._states:
            self._states[plan_id] = {
                "state": "SCHEDULED",
                "started_at": None,
                "paused_at": None,
                "updated_at": None,
            }

    def get_state(self, plan_id: str) -> Dict[str, Any]:
        self._ensure(plan_id)
        return copy.deepcopy(self._states[plan_id])

    def transit(self, plan_id: str, new_state: str) -> tuple[bool, str]:
        """尝试状态转移，返回 (success, message)。支持幂等：当前状态已是目标状态时直接返回成功。"""
        if new_state not in self.VALID_STATES:
            return False, f"非法状态: {new_state}"

        self._ensure(plan_id)
        current = self._states[plan_id]["state"]
        if current == new_state:
            return True, f"状态已是 {new_state}"
        if new_state not in self.TRANSITIONS.get(current, set()):
            return False, f"不允许从 {current} 转移到 {new_state}"

        now = datetime.now(timezone.utc).isoformat()
        self._states[plan_id]["state"] = new_state
        self._states[plan_id]["updated_at"] = now

        if new_state == "ACTIVE":
            if self._states[plan_id]["started_at"] is None:
                self._states[plan_id]["started_at"] = now
        elif new_state == "PAUSED":
            self._states[plan_id]["paused_at"] = now

        return True, f"状态已更新: {current} -> {new_state}"

    def reset(self, plan_id: str):
        """重置状态"""
        self._states[plan_id] = {
            "state": "SCHEDULED",
            "started_at": None,
            "paused_at": None,
            "updated_at": None,
        }

    def init_state_from_plan(self, plan_id: str, plan: Dict[str, Any]):
        """
        根据 plan 中的 action 状态推断 plan 整体运行时状态，并初始化内存状态。
        仅在尚未追踪该 plan 时执行（避免覆盖用户已触发的控制操作）。
        """
        if plan_id in self._states:
            return
        action_states = set()
        # 从 car_actions 收集
        for ca in plan.get("car_actions", []):
            action_states.add(ca.get("state", "SCHEDULED"))
        # 从 vehicle_summary 收集
        for vs in plan.get("vehicle_summary", []):
            for stage in vs.get("stages", []):
                for action in stage.get("actions", []):
                    action_states.add(action.get("state", "SCHEDULED"))
        # 推断整体状态：有 ACTIVE 则为 ACTIVE；无 ACTIVE 有 PAUSED 则为 PAUSED；全部为 DONE 则为 DONE；否则 SCHEDULED
        inferred = "SCHEDULED"
        if "ACTIVE" in action_states:
            inferred = "ACTIVE"
        elif "PAUSED" in action_states:
            inferred = "PAUSED"
        elif action_states == {"DONE"}:
            inferred = "DONE"
        self._states[plan_id] = {
            "state": inferred,
            "started_at": None,
            "paused_at": None,
            "updated_at": None,
        }


# 全局单例
action_runtime = ActionSequenceRuntime()


# ==================== Plan → MissionService mission_data 转换 ====================


def _resource_type_to_vehicle_type(resource_type: str) -> str:
    """把 plan.teams[].vehicles[].resource_type 归一化为内部车型标识"""
    rt = (resource_type or "").strip().lower().replace("-", "_")
    mapping = {
        "fire_support_ugv": "fire_support",
        "recon_strike_ugv": "recon_strike",
        "patrol_ugv": "patrol",
        "electronic_ugv": "electronic",
        "air_ground_uav": "air_ground",
        "air_ground_ugv": "air_ground",
    }
    return mapping.get(rt, "")


def _build_vid_vehicle_type_map(plan: Dict[str, Any]) -> Dict[str, str]:
    """建立 vid -> vehicle_type 映射；优先 plan.teams，其次 vehicle_summary，最后按 vid 推断"""
    result: Dict[str, str] = {}
    # 1) 从 plan.teams 读取 resource_type
    for team in plan.get("teams", []) or []:
        if not isinstance(team, dict):
            continue
        for v in team.get("vehicles", []) or []:
            if isinstance(v, dict) and v.get("vid"):
                result[v["vid"]] = _resource_type_to_vehicle_type(v.get("resource_type", ""))
        if team.get("vid"):
            result[team["vid"]] = _resource_type_to_vehicle_type(team.get("resource_type", ""))

    # 2) 从 vehicle_summary 兜底（数据服务器可能只在 vehicle_summary 中带 resource_type）
    for vsum in plan.get("vehicle_summary", []) or []:
        vid = vsum.get("vid", "")
        if not vid:
            continue
        rt = vsum.get("resource_type", "")
        if rt:
            result[vid] = _resource_type_to_vehicle_type(rt)
        elif vid not in result:
            result[vid] = _resource_type_to_vehicle_type(_infer_resource_type_from_vid(vid))

    # 3) 仍有缺失则按 vid 推断
    for vid in result:
        if not result[vid]:
            result[vid] = _resource_type_to_vehicle_type(_infer_resource_type_from_vid(vid))
    return result


def _resolve_sid(vehicle_type: str, action_type: str, name: str = "") -> int:
    """根据车型 + action_type 解析协议 sid；无法解析时 fallback 到名称关键词推断

    action_type 统一按小写处理，兼容旧版连字符命名与新版首字母大写命名。
    命名来源：docs/00-行动序列参考文档/装备行动序列数据结构 - 大模型侧定义-from昕鸣.md
    """
    t = (action_type or "").strip().lower()
    vt = (vehicle_type or "").strip().lower()

    # 底盘类 / 通用元任务（所有车型通用）
    chassis_map = {
        "auto-move": 1,
        "follow-move": 2,
        "silent-guard": 4,
        "set-return-point": 5,
        "return-to-base": 6,
        "formation-move": 7,
        "manual-task": 8,
        "pose-adjust": 9,
    }
    if t in chassis_map:
        return chassis_map[t]

    # 火力车 (sid 20~26，不含整车模式/自定义打击)
    if vt == "fire_support":
        return {
            "lens-recon": 21,
            "search-and-shoot": 22,
            "recon-strike": 22,
            "rocket-launch": 23,
            "loitering-munition-launch": 24,
            "7.62mm-gun-shot": 25,
            "gun-shot": 25,
        }.get(t)

    # 侦打车 (sid 30~37，不含整车模式/自定义打击)
    if vt == "recon_strike":
        return {
            "lens-recon": 31,
            "search-and-shoot": 32,
            "recon-strike": 32,
            "40mm-gun-launch": 33,
            "at-missile-launch": 34,
            "7.62mm-gun-shot": 35,
            "gun-shot": 35,
            "laser-illumination": 36,
        }.get(t)

    # 巡逻车 (sid 50~56，不含整车模式/自定义打击)
    if vt == "patrol":
        return {
            "lens-recon": 51,
            "search-and-shoot": 52,
            "recon-strike": 52,
            "7.62mm-gun-shot": 53,
            "gun-shot": 53,
            "sound-expel": 54,
            "acoustic-deterrence": 54,
            "light-expel": 55,
            "light-deterrence": 55,
        }.get(t)

    # 电磁车 (sid 40~48，不含整车模式)
    if vt == "electronic":
        return {
            "em-recon": 41,
            "electronic-recon": 41,
            "em-interference": 42,
            "electronic-jamming": 42,
            "payload-silent": 48,
        }.get(t)

    # 空地车 (sid 70~79)
    if vt == "air_ground":
        return {
            "air-recon": 71,
            "air_recon": 71,
            "ag_air_recon": 71,
        }.get(t)

    # 对无法识别车型的车辆，底盘类元任务已经返回 sid；
    # 若仍无法解析，按名称关键词兜底推断。
    return _action_name_to_sid(name)


def _action_name_to_sid(name: str) -> int:
    """根据 action 名称关键词推断元任务 sid"""
    if not name:
        return 1
    n = name.lower()
    if "静默" in n or "值守" in n or "驻守" in n:
        return 4
    if "设置返航点" in n:
        return 5
    if "返航" in n or "返回基地" in n or "回基地" in n:
        return 6
    if "人工" in n or "保障" in n:
        return 8
    if "跟随" in n:
        return 2
    if "编队" in n:
        return 7
    if "姿态" in n or "转向" in n or "车姿" in n:
        return 9
    if "40炮" in n or "40mm" in n:
        return 33
    if "红箭" in n or "导弹" in n:
        return 34
    if "激光" in n or "照射" in n:
        return 36
    if "强声" in n or "声波" in n or "声音" in n:
        return 54
    if "强光" in n or "灯光" in n:
        return 55
    if "电磁侦察" in n or "电侦" in n or "频谱" in n:
        return 41
    if "电磁" in n or "干扰" in n or "突击" in n:
        return 42
    if "载荷静默" in n:
        return 48
    if "火箭" in n:
        return 23
    if "巡飞" in n:
        return 24
    if "7.62" in n or "机枪" in n or "枪" in n:
        return 25
    if "侦察打击" in n or "搜索打击" in n:
        return 22
    if "光电" in n or "白光" in n or "红外" in n or "鹰眼" in n:
        return 21
    if "空中侦察" in n or "空中" in n:
        return 71
    if "通信中继" in n or "中继" in n:
        return 61
    # 默认：自主机动
    return 1


def _to_int_scaled(value, scale: float = 1.0) -> int:
    try:
        return int(float(value or 0) * scale)
    except (TypeError, ValueError):
        return 0


def _build_path_points(points):
    """自主机动/编队机动路径点：lon/lat 缩放 1e6，alt 缩放 10"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        result.append({
            "lon": _to_int_scaled(pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0), 1e6),
            "lat": _to_int_scaled(pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0), 1e6),
            "alt": _to_int_scaled(pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0), 10),
            "radius": pt.get("radius", -1),
            "type": pt.get("type", 1),
        })
    return result


def _build_area_points(points):
    """侦察/电磁区域点：lon/lat 缩放 1e6，alt 缩放 10"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        result.append({
            "lon": _to_int_scaled(pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0), 1e6),
            "lat": _to_int_scaled(pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0), 1e6),
            "alt": _to_int_scaled(pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0), 10),
        })
    return result


def _build_strike_points(points):
    """打击类目标点公共字段"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        result.append({
            "lon": _to_int_scaled(pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0), 1e6),
            "lat": _to_int_scaled(pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0), 1e6),
            "alt": _to_int_scaled(pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0), 10),
            "tart": pt.get("tart", 0),
            "attr": pt.get("attr", 0),
            "thr": pt.get("thr", 0),
            "dam": pt.get("dam", 0),
            "blk": pt.get("blk", 0),
            "figt": pt.get("figt", 0),
            "sug": pt.get("sug", 0),
        })
    return result


def _build_air_recon_points(points):
    """空中侦察航路点：lon/lat 缩放 1e6，alt 缩放 10，保留飞行/相机扩展字段"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        result.append({
            "lon": _to_int_scaled(pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0), 1e6),
            "lat": _to_int_scaled(pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0), 1e6),
            "alt": _to_int_scaled(pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0), 10),
            "type": pt.get("type", 0),
            "speed": int(float(pt.get("speed", 0))),
            "camera": pt.get("camera", 1),
            "gimpitch": int(float(pt.get("gimpitch", 36100))),
            "gimyaw": int(float(pt.get("gimyaw", 36100))),
            "action": pt.get("action", 1),
            "playaw": int(float(pt.get("playaw", 36100))),
            "zoom": int(float(pt.get("zoom", 0))),
            "loiter": int(float(pt.get("loiter", 0))),
        })
    return result


def _build_direct(direct):
    """定向探测参数"""
    if not isinstance(direct, dict):
        return None
    return {
        "type": direct.get("type", 1),
        "cent": direct.get("cent", 36100),
        "sear": direct.get("sear", 36100),
        "up": direct.get("up", 9999),
        "down": direct.get("down", 9999),
        "dist": direct.get("dist", 9999),
        "sens": direct.get("sens", 0),
    }


def _build_service_from_action(action: Dict[str, Any], vehicle_type: str = "") -> Dict[str, Any]:
    """将单个 action 转换为 mission_data act.service"""
    name = action.get("name", "")
    description = action.get("description", "")
    param = action.get("param") or {}
    action_type = (action.get("action_type") or "").strip()

    sid = _resolve_sid(vehicle_type, action_type, name)

    # sid = 1: 自主机动 / 循迹机动
    if sid == 1:
        points = _build_path_points(param.get("points"))
        if len(points) < 2:
            # fallback：兼容旧 waypoints 字段或占位
            wps = param.get("waypoints")
            if isinstance(wps, list) and len(wps) >= 2:
                points = _build_path_points(wps)
        if len(points) < 2:
            points = [
                {"lon": 116397128, "lat": 39909231, "alt": 435, "radius": -1, "type": 1},
                {"lon": 116397500, "lat": 39909500, "alt": 435, "radius": -1, "type": 1},
            ]
        return {
            "sid": 1,
            "points": points,
            "limited_speed": param.get("limited_speed", 20),
            "safe_mode": param.get("safe_mode", 0),
            "loop_mode": param.get("loop_mode", 0),
        }

    # sid = 2: 跟随机动
    if sid == 2:
        return {
            "sid": 2,
            "x": param.get("x", 960),
            "y": param.get("y", 540),
            "width": param.get("width", 1920),
            "height": param.get("height", 1080),
            "distance": param.get("distance", 10),
            "limited_speed": param.get("limited_speed", 15),
            "safe_mode": param.get("safe_mode", 0),
            "strategy": param.get("strategy", 0),
        }

    # sid = 4: 静默值守
    if sid == 4:
        return {"sid": 4, "time": param.get("time", 300)}

    # sid = 5: 设置返航点
    if sid == 5:
        return {"sid": 5}

    # sid = 6: 开启返航
    if sid == 6:
        return {"sid": 6}

    # sid = 7: 编队机动
    if sid == 7:
        return {
            "sid": 7,
            "points": _build_path_points(param.get("points")),
            "limited_speed": param.get("limited_speed", 20),
            "formation_mode": param.get("formation_mode", 0),
            "safe_mode": param.get("safe_mode", 0),
        }

    # sid = 8: 人工任务
    if sid == 8:
        return {"sid": 8, "type": param.get("type", 1)}

    # sid = 9: 姿态调整 / 车姿调整
    if sid == 9:
        return {
            "sid": 9,
            "pose": param.get("pose", [9000, 0, 0]),
            "pose_deviation": param.get("pose_deviation", [36100, 9100, 9100]),
            "limitd_speed": param.get("limited_speed", 10),
            "safe_mode": param.get("safe_mode", 0),
        }

    # sid = 21/31/51: 光电侦察
    if sid in (21, 31, 51):
        service = {
            "sid": sid,
            "type": param.get("type", 2),
            "mode": param.get("mode", 3),
            "time": param.get("time", 120),
            "area": _build_area_points(param.get("area")),
        }
        direct = _build_direct(param.get("direct"))
        if direct and param.get("mode") == 4:
            service["direct"] = direct
        return service

    # sid = 22/32: 侦察打击（火力车/侦打车）
    if sid in (22, 32):
        return {
            "sid": sid,
            "time": param.get("time", 180),
            "area": _build_area_points(param.get("area")),
        }

    # sid = 52: 巡逻车侦察打击
    if sid == 52:
        return {
            "sid": 52,
            "time": param.get("time", 180),
            "tarty": param.get("tarty", 0),
            "attr": param.get("attr", 0),
            "thr": param.get("thr", 0),
            "dam": param.get("dam", 0),
            "blk": param.get("blk", 0),
            "figt": param.get("figt", 0),
            "sug": param.get("sug", 0),
            "ammo": param.get("ammo", 0),
            "strategy": param.get("strategy", 0),
            "area": _build_area_points(param.get("area")),
        }

    # sid = 23/24/25/33/35/53: 各类打击（公共字段）
    if sid in (23, 24, 25, 33, 35, 53):
        service = {
            "sid": sid,
            "time": param.get("time", 60),
            "sort": param.get("sort", 0),
            "num": param.get("num", len(param.get("points", [])) or 1),
            "points": _build_strike_points(param.get("points")),
        }
        # 火箭弹支持区域打击 type 字段
        if sid == 23:
            service["type"] = param.get("type", 1)
        return service

    # sid = 34: 红箭 13 导弹打击
    if sid == 34:
        return {
            "sid": 34,
            "time": param.get("time", 60),
            "sort": param.get("sort", 1),
            "num": param.get("num", len(param.get("points", [])) or 1),
            "points": _build_strike_points(param.get("points")),
        }

    # sid = 36: 激光照射
    if sid == 36:
        return {
            "sid": 36,
            "time": param.get("time", 120),
            "act": param.get("act", 1),
            "param1": param.get("param1", 0),
            "param2": param.get("param2", 0),
            "ene": param.get("ene", 80),
            "freq": param.get("freq", 1000),
            "meat": param.get("meat", 30),
            "delay": param.get("delay", 5),
            "max": param.get("max", 10),
            "type": param.get("type", 1),
            "strategy": param.get("strategy", 0),
            "lon": _to_int_scaled(param.get("lon", 0), 1e6),
            "lat": _to_int_scaled(param.get("lat", 0), 1e6),
            "alt": _to_int_scaled(param.get("alt", 0), 10),
        }

    # sid = 54/55: 强声拒止 / 强光拒止
    if sid in (54, 55):
        return {
            "sid": sid,
            "time": param.get("time", 60),
            "tarty": param.get("tarty", 0),
            "attr": param.get("attr", 0),
            "thr": param.get("thr", 0),
            "dam": param.get("dam", 0),
            "blk": param.get("blk", 0),
            "figt": param.get("figt", 0),
            "sug": param.get("sug", 0),
            "ammo": param.get("ammo", 0),
            "strategy": param.get("strategy", 0),
            "area": _build_area_points(param.get("area")),
        }

    # sid = 71: 空中侦察
    if sid == 71:
        return {
            "sid": 71,
            "type": param.get("type", 2),
            "mode": param.get("mode", 1),
            "time": param.get("time", 120),
            "points1": _build_air_recon_points(param.get("points1")),
            "points2": _build_air_recon_points(param.get("points2")),
            "points3": _build_air_recon_points(param.get("points3")),
        }

    # sid = 41: 电磁侦察
    if sid == 41:
        service = {
            "sid": 41,
            "mode": param.get("mode", 3),
            "time": param.get("time", 300),
            "num": param.get("num", 1),
            "freqtype": param.get("freqtype", 62),
            "frequency": param.get("frequency", []),
            "area": _build_area_points(param.get("area")),
        }
        direct = _build_direct(param.get("direct"))
        if direct and param.get("mode") == 4:
            service["direct"] = direct
        return service

    # sid = 42: 电磁突击 / 电磁干扰
    if sid == 42:
        service = {
            "sid": 42,
            "mode": param.get("mode", 3),
            "time": param.get("time", 300),
            "sort": param.get("sort", 1),
            "num": param.get("num", 1),
            "freqtype": param.get("freqtype", 62),
            "frequency": param.get("frequency", []),
            "area": _build_area_points(param.get("area")),
            "protect": param.get("protect", {}),
        }
        direct = _build_direct(param.get("direct"))
        if direct and param.get("mode") == 4:
            service["direct"] = direct
        return service

    # sid = 48: 载荷静默
    if sid == 48:
        return {"sid": 48, "time": param.get("time", 300)}

    # 兜底
    return {"sid": 1, "points": [], "limited_speed": 20, "safe_mode": 0, "loop_mode": 0}


def build_mission_data(
    plan: Dict[str, Any],
    vehicle_vmfs: Optional[Dict[str, int]] = None,
    vehicle_ips: Optional[Dict[str, str]] = None,
    tid: Optional[int] = None,
    target_vid: Optional[str] = None,
) -> Dict[str, Any]:
    """
    将 plan 转换为 MissionService 的 mission_data 格式。

    Args:
        plan: 方案详情 dict（含 stages / team_actions 或 vehicle_summary）
        vehicle_vmfs: vid -> vmf 数字编号 映射，例如 {"无人车A": 99076716}
        vehicle_ips: vid -> IP 映射，例如 {"无人车A": "192.168.1.11"}
        tid: 任务编号，默认用 plan_id 哈希

    Returns:
        {"task": {...}} 结构，可直接放入 payload.args.mission_data
    """
    plan_id = plan.get("plan_id", "")
    title = plan.get("title", "")

    # 建立 vid -> vehicle_type 映射
    vid_vehicle_type_map = _build_vid_vehicle_type_map(plan)

    # 生成 tid
    if tid is None:
        # 尝试从 plan_id 提取数字，否则哈希
        nums = re.findall(r"\d+", plan_id)
        if nums:
            tid = int("".join(nums)[:10]) or 10001
        else:
            h = hashlib.md5(plan_id.encode()).hexdigest()[:8]
            tid = int(h, 16) % 90000000 + 10000000

    # 时间
    now = datetime.now(timezone.utc)
    start_str = now.strftime("%Y-%m-%d %H:%M:%S")
    end_str = (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

    # 提取所有车辆 actions
    # 兼容两种数据结构：
    #   1) plan.stages[].team_actions{team_id: [{vid, actions}]}
    #   2) plan.vehicle_summary[].stages[].actions
    vehicle_actions_map: Dict[str, List[Dict[str, Any]]] = {}

    stages = plan.get("stages", [])
    for stage in stages:
        team_actions = stage.get("team_actions", {})
        if isinstance(team_actions, dict):
            for team_id, vehicles in team_actions.items():
                for vehicle in vehicles:
                    vid = vehicle.get("vid", "")
                    actions = vehicle.get("actions", [])
                    car_action_type = vehicle.get("action_type", "")
                    if vid and actions:
                        if vid not in vehicle_actions_map:
                            vehicle_actions_map[vid] = []
                        for a in actions:
                            # 优先保留 action 自带的 action_type；car_actions 层级有值时才覆盖
                            at = car_action_type or a.get("action_type", "")
                            vehicle_actions_map[vid].append(dict(a, action_type=at))
        elif isinstance(team_actions, list):
            for ta in team_actions:
                team_id = ta.get("team_id", "")
                vehicles = ta.get("team_actions", [])
                for vehicle in vehicles:
                    vid = vehicle.get("vid", "")
                    actions = vehicle.get("actions", [])
                    car_action_type = vehicle.get("action_type", "")
                    if vid and actions:
                        if vid not in vehicle_actions_map:
                            vehicle_actions_map[vid] = []
                        for a in actions:
                            at = car_action_type or a.get("action_type", "")
                            vehicle_actions_map[vid].append(dict(a, action_type=at))

    # 也兼容 vehicle_summary 结构
    vehicle_summary = plan.get("vehicle_summary", [])
    for vsum in vehicle_summary:
        vid = vsum.get("vid", "")
        for stage in vsum.get("stages", []):
            actions = stage.get("actions", [])
            # vehicle_summary 中的 stage 没有 action_type，尝试从 action 自身读取
            if vid and actions:
                if vid not in vehicle_actions_map:
                    vehicle_actions_map[vid] = []
                vehicle_actions_map[vid].extend(actions)

    # 去重并排序（按 action_seq）
    for vid in vehicle_actions_map:
        seen = set()
        uniq = []
        for a in vehicle_actions_map[vid]:
            # action_id 为 None/空时用 action_seq 兜底，避免全部误判为同一 action
            aid = a.get("action_id") or a.get("action_seq", id(a))
            if aid not in seen:
                seen.add(aid)
                uniq.append(a)
        uniq.sort(key=lambda x: x.get("action_seq", 0))
        vehicle_actions_map[vid] = uniq

    # 构建 vehicles（如指定 target_vid 则只下发该车辆的行动序列）
    mission_vehicles = []
    for vid, actions in vehicle_actions_map.items():
        if target_vid and vid.replace("equipment:", "") != target_vid.replace("equipment:", ""):
            continue
        vmf = (vehicle_vmfs or {}).get(vid)
        if vmf is None:
            # 尝试 vid 本身就是数字
            try:
                vmf = int(vid)
            except (ValueError, TypeError):
                vmf = 99076716  # 兜底：ZD01 的示例 vmf

        vip = (vehicle_ips or {}).get(vid, "192.168.1.11")
        num = len(actions)

        acts = []
        vehicle_type = vid_vehicle_type_map.get(vid, "")
        for idx, action in enumerate(actions, start=1):
            service = _build_service_from_action(action, vehicle_type)
            act = {
                "aid": idx,
                "num": num,
                "vid": [vmf],
                "vip": [vip],
                "strategy": 2,
                "start": start_str,
                "end": end_str,
                "premise": list(range(1, idx)),  # 前置为前面所有 action
                "endwith": -1,
                "level": 0,
                "service": service,
            }
            acts.append(act)

        mission_vehicles.append({
            "vid": vmf,
            "cnt": f"{vid}任务",
            "num": num,
            "acts": acts,
        })

    mission_data = {
        "task": {
            "tid": tid,
            "type": 0,
            "cnt": title or f"任务{plan_id}",
            "start": start_str,
            "end": end_str,
            "vehicles": mission_vehicles,
        }
    }
    return mission_data


def build_mission_payload(
    plan: Dict[str, Any],
    vehicle_vmfs: Optional[Dict[str, int]] = None,
    vehicle_ips: Optional[Dict[str, str]] = None,
    tid: Optional[int] = None,
    target_vid: Optional[str] = None,
) -> Dict[str, Any]:
    """
    构建完整的 MissionService send_mission payload。

    Returns:
        {"service": "MissionService", "action": "send_mission", "args": {"mission_data": {...}}}
    """
    mission_data = build_mission_data(plan, vehicle_vmfs, vehicle_ips, tid, target_vid)
    return {
        "service": "MissionService",
        "action": "send_mission",
        "args": {
            "mission_data": mission_data,
        },
    }


# ==================== MissionService control_mission 相关 ====================


def _plan_id_to_tid(plan_id: str) -> int:
    """从 plan_id 提取或生成 tid"""
    nums = re.findall(r"\d+", plan_id)
    if nums:
        return int("".join(nums)[:10]) or 10001
    h = hashlib.md5(plan_id.encode()).hexdigest()[:8]
    return int(h, 16) % 90000000 + 10000000


def get_first_vid(plan: Dict[str, Any]) -> str:
    """
    从 plan 中提取第一个 vid（车辆标识）。
    兼容多种数据结构：vehicle_summary / stages[].team_actions / stages[].team_actions{team_id: [...]}
    """
    # 1) 优先从 vehicle_summary 取
    vehicle_summary = plan.get("vehicle_summary", [])
    if isinstance(vehicle_summary, list) and len(vehicle_summary) > 0:
        vid = vehicle_summary[0].get("vid", "")
        if vid:
            return vid

    # 2) 从 stages[].team_actions 取
    stages = plan.get("stages", [])
    for stage in stages:
        team_actions = stage.get("team_actions", {})
        # dict 格式: {team_id: [{vid, actions}]}
        if isinstance(team_actions, dict):
            for team_id, vehicles in team_actions.items():
                if isinstance(vehicles, list) and len(vehicles) > 0:
                    vid = vehicles[0].get("vid", "")
                    if vid:
                        return vid
        # list 格式: [{team_id, team_actions: [{vid, actions}]}]
        elif isinstance(team_actions, list):
            for ta in team_actions:
                vehicles = ta.get("team_actions", [])
                if isinstance(vehicles, list) and len(vehicles) > 0:
                    vid = vehicles[0].get("vid", "")
                    if vid:
                        return vid

    # 3) fallback
    return "ZD01"


def build_control_mission_payload(
    plan_id: str,
    task_control: int,
    vehicle_vid: Optional[str] = None,
) -> tuple[str, Dict[str, Any]]:
    """
    构建 MissionService control_mission 的 payload。

    Returns:
        (topic, payload)
    """
    tid = _plan_id_to_tid(plan_id)

    # 如果传了 vehicle_vid 则直接用，否则从 plan 详情里取
    if vehicle_vid:
        vid = vehicle_vid
    else:
        plan = get_plan_detail(plan_id)
        vid = get_first_vid(plan) if plan else "ZD01"
    # 去掉 equipment: 前缀（如 equipment:XL01 → XL01）
    vid = vid.replace("equipment:", "") if vid else vid

    topic = f"op/t01/g01/v{vid}/cmd/MissionService/control_mission"
    payload = {
        "service": "MissionService",
        "action": "control_mission",
        "args": {
            "taskid": tid,
            "aid": 0,
            "task_control": task_control,
            "action_control": 0,
        },
    }
    return topic, payload


def publish_control_mission(
    plan_id: str,
    task_control: int,
    vehicle_vid: Optional[str] = None,
) -> tuple[bool, str]:
    """
    通过 Zenoh 发送 control_mission。

    Args:
        plan_id: 方案 ID
        task_control: 1=开始, 2=暂停, 3=继续, 4=停止
        vehicle_vid: 可选，指定车辆 vid；不指定则自动从 plan 中取第一个 vid

    Returns:
        (success, message)
    """
    import json

    topic, payload = build_control_mission_payload(plan_id, task_control, vehicle_vid)
    print(f"[ZENOH-CTRL] task_control={task_control} | topic={topic} | tid={payload['args']['taskid']}")

    ok = zenoh_client.publish(topic, payload)
    if ok:
        return True, f"control_mission 已下发 | topic={topic} | task_control={task_control}"
    else:
        err = zenoh_client.get_last_zenoh_error()
        print(f"[ZENOH-CTRL] publish failed: {err}")
        return False, f"Zenoh 下发失败: {err}"


# ========== 车辆类型与资源池映射 ==========

VEHICLE_TYPE_DISPLAY_NAMES = {
    "Fire-Support-UGV": "火力车",
    "Recon-Strike-UGV": "侦打车",
    "Patrol-UGV": "巡逻车",
    "Electronic-UGV": "电磁车",
    "Air-Ground-UAV": "空地车",
}

# 各车型默认支持的载荷 action_type（用于前端新建行动序列时初始化节点）。
# 底盘类元任务（Auto-Move/Follow-Move/Silent-Guard 等）对所有车型通用，不在这里维护。
VEHICLE_ACTION_TYPES = {
    "Fire-Support-UGV": [
        "Lens-Recon", "Search-And-Shoot", "7.62mm-Gun-Shot",
        "Rocket-Launch", "Loitering-Munition-Launch",
    ],
    "Recon-Strike-UGV": [
        "Lens-Recon", "Search-And-Shoot", "40mm-Gun-Launch",
        "AT-Missile-Launch", "7.62mm-Gun-Shot", "Laser-Illumination",
    ],
    "Patrol-UGV": [
        "Lens-Recon", "Search-And-Shoot", "7.62mm-Gun-Shot",
        "Sound-Expel", "Light-Expel",
    ],
    "Electronic-UGV": ["EM-Recon", "EM-Interference", "Payload-Silent"],
    "Air-Ground-UAV": ["Air-Recon"],
}

# 资源池返回的 resource_type / model_type.description -> 内部车型映射
_RESOURCE_TYPE_TO_VEHICLE = {
    # 常见 resource_type 写法
    "Fire-Support-UGV": "Fire-Support-UGV",
    "Recon-Strike-UGV": "Recon-Strike-UGV",
    "Patrol-UGV": "Patrol-UGV",
    "Electronic-UGV": "Electronic-UGV",
    "Air-Ground-UAV": "Air-Ground-UAV",
    # 中文描述兜底
    "无人火力车": "Fire-Support-UGV",
    "无人侦察车": "Recon-Strike-UGV",
    "无人巡逻车": "Patrol-UGV",
    "无人电磁车": "Electronic-UGV",
    "无人空地车": "Air-Ground-UAV",
    "空地车": "Air-Ground-UAV",
}


def _infer_vehicle_type(equipment: Dict[str, Any]) -> str:
    """从资源池 equipment 记录推断内部车辆类型。"""
    # 1) 优先使用 resource_type
    rt = (equipment.get("resource_type") or "").strip()
    if rt in VEHICLE_TYPE_DISPLAY_NAMES:
        return rt
    if rt in _RESOURCE_TYPE_TO_VEHICLE:
        return _RESOURCE_TYPE_TO_VEHICLE[rt]

    # 2) 其次 model_type.description / model_type.type
    model = equipment.get("model_type") or {}
    for key in ("description", "type"):
        md = (model.get(key) or "").strip()
        if md in VEHICLE_TYPE_DISPLAY_NAMES:
            return md
        if md in _RESOURCE_TYPE_TO_VEHICLE:
            return _RESOURCE_TYPE_TO_VEHICLE[md]

    # 3) 兜底：返回原始 resource_type，让前端自行决定展示/映射
    return rt or "Unknown"


def _build_fallback_vehicles() -> List[Dict[str, Any]]:
    """资源池不可达时的本地调试 fallback：返回五型无人车。"""
    return [
        {
            "vid": "equipment:recon-strike-01",
            "resource_name": "侦打车-01",
            "resource_type": "Recon-Strike-UGV",
            "display_name": VEHICLE_TYPE_DISPLAY_NAMES["Recon-Strike-UGV"],
            "supported_action_types": VEHICLE_ACTION_TYPES["Recon-Strike-UGV"],
            "is_mock": True,
        },
        {
            "vid": "equipment:fire-support-01",
            "resource_name": "火力车-01",
            "resource_type": "Fire-Support-UGV",
            "display_name": VEHICLE_TYPE_DISPLAY_NAMES["Fire-Support-UGV"],
            "supported_action_types": VEHICLE_ACTION_TYPES["Fire-Support-UGV"],
            "is_mock": True,
        },
        {
            "vid": "equipment:patrol-01",
            "resource_name": "巡逻车-01",
            "resource_type": "Patrol-UGV",
            "display_name": VEHICLE_TYPE_DISPLAY_NAMES["Patrol-UGV"],
            "supported_action_types": VEHICLE_ACTION_TYPES["Patrol-UGV"],
            "is_mock": True,
        },
        {
            "vid": "equipment:electronic-01",
            "resource_name": "电磁车-01",
            "resource_type": "Electronic-UGV",
            "display_name": VEHICLE_TYPE_DISPLAY_NAMES["Electronic-UGV"],
            "supported_action_types": VEHICLE_ACTION_TYPES["Electronic-UGV"],
            "is_mock": True,
        },
        {
            "vid": "equipment:air-ground-01",
            "resource_name": "空地车-01",
            "resource_type": "Air-Ground-UAV",
            "display_name": VEHICLE_TYPE_DISPLAY_NAMES["Air-Ground-UAV"],
            "supported_action_types": VEHICLE_ACTION_TYPES["Air-Ground-UAV"],
            "is_mock": True,
        },
    ]


def _transform_equipment_to_vehicle(equipment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把资源池 equipment 记录转换为前端需要的 vehicle 结构。"""
    rid = equipment.get("resource_id", "")
    if not rid:
        return None

    vehicle_type = _infer_vehicle_type(equipment)
    if not vehicle_type or vehicle_type == "Unknown":
        # 无法识别的类型，跳过（或保留原始类型由前端处理）
        return None

    return {
        "vid": rid,
        "resource_name": equipment.get("resource_name") or rid.replace("equipment:", ""),
        "resource_type": vehicle_type,
        "display_name": VEHICLE_TYPE_DISPLAY_NAMES.get(vehicle_type, vehicle_type),
        "supported_action_types": VEHICLE_ACTION_TYPES.get(vehicle_type, []),
        "online_status": equipment.get("online_status") or "UNKNOWN",
        "is_mock": False,
    }


def _fetch_vehicles_from_resource_pool() -> List[Dict[str, Any]]:
    """内部：从资源池获取车辆列表。优先 online，若没有则回退全部 equipment。"""
    # 1) 优先获取 online 车辆
    data = _http_get_resource_pool(
        "/api/v1/resource_pool/resources",
        params={"is_online": "true", "entity_kind": "equipment", "limit": 100},
        silent=True,
    )
    items = data if isinstance(data, list) else data.get("items") or data.get("data") or []

    # 2) 没有 online 车辆时，尝试获取全部 equipment（可能资源池未标记在线状态）
    if not items:
        data = _http_get_resource_pool(
            "/api/v1/resource_pool/resources",
            params={"entity_kind": "equipment", "limit": 100},
            silent=True,
        )
        items = data if isinstance(data, list) else data.get("items") or data.get("data") or []

    result = []
    for item in items:
        vehicle = _transform_equipment_to_vehicle(item)
        if vehicle:
            result.append(vehicle)
    return result


def query_online_vehicles() -> List[Dict[str, Any]]:
    """从资源池查询当前已连接（online）的无人车列表。

    资源池服务独立部署在 28800 端口（与 task_pool 28801 区分）。
    资源池不可达或没有可识别车辆时返回本地调试 fallback 车辆列表。
    """
    result = _fetch_vehicles_from_resource_pool()
    if result:
        return result
    print("[AS-DEBUG] query_online_vehicles: no vehicles from resource_pool, use fallback")
    return _build_fallback_vehicles()


def query_online_vehicles_operator() -> List[Dict[str, Any]]:
    """从资源池查询当前已连接（online）的无人车列表（操控席视角，资源池服务共用）。"""
    result = _fetch_vehicles_from_resource_pool()
    if result:
        return result
    print("[AS-DEBUG] query_online_vehicles_operator: no vehicles from resource_pool, use fallback")
    return _build_fallback_vehicles()


# ==================== 操控席数据服务端接口 ====================


def query_plans_operator(limit: int = 20) -> List[Dict[str, Any]]:
    """向操控席数据服务器查询行动方案列表 — POST /resources/query（静默模式）。
    服务端不可达或为空时回退本地 task_pool；本地 fake 调测方案合并到列表最前（调试用）。"""
    data = _http_post_operator(
        "/api/v1/task_pool/resources/query",
        {"task_type": "PLAN", "limit": limit},
        silent=True,
    )
    items = []
    if data is not None and isinstance(data, list):
        items = data[:limit]
        print(f"[AS-DEBUG] query_plans_operator: data is list, len={len(data)}, limit={limit}")
    elif data is not None and isinstance(data, dict):
        raw_items = data.get("items") or data.get("data") or []
        items = raw_items[:limit]
        print(f"[AS-DEBUG] query_plans_operator: data is dict, keys={list(data.keys())}, items_len={len(raw_items)}, limit={limit}")
    else:
        print(f"[AS-DEBUG] query_plans_operator: data is None or type={type(data)}")

    # 合并本地 fake 调测方案（FAKE_ACTION_SEQUENCE_LOCAL_001），方便本地调试。
    # TODO: 后续删除本地假数据逻辑时，移除此段合并代码。
    local_items = task_pool.query(task_type="PLAN", limit=limit)
    FAKE_PLAN_ID = "FAKE_ACTION_SEQUENCE_LOCAL_001"
    if not items:
        print("[AS-DEBUG] query_plans_operator fallback to local task_pool")
        items = local_items
    else:
        server_ids = {
            (item.get("plan_id") or item.get("resource_id", "").replace("plan:", ""))
            for item in items
        }
        for local_item in local_items:
            local_id = local_item.get("plan_id") or local_item.get("resource_id", "").replace("plan:", "")
            # 仅合并本地 fake 调测方案，不要把真实 plan 的本地缓存插入列表
            if local_id == FAKE_PLAN_ID and local_id not in server_ids:
                items.insert(0, local_item)

    result = []
    for item in items:
        item = _normalize_plan_field_names(item)
        tactic = item.get("tactic") or {}
        if not isinstance(tactic, dict):
            tactic = {}
        title = (
            item.get("title")
            or tactic.get("title")
            or item.get("plan_id")
            or ""
        )
        state = item.get("state") or "DRAFT"
        result.append({
            "plan_id": item.get("plan_id") or item.get("resource_id", "").replace("plan:", ""),
            "resource_id": item.get("resource_id", ""),
            "title": title,
            "description": item.get("description") or "",
            "state": state,
            "teams_count": len(item.get("teams") or []),
            "stages_count": len(item.get("stages") or []),
        })
    return result


def get_plan_detail_operator(plan_id: str) -> Optional[Dict[str, Any]]:
    """向操控席数据服务器获取方案详情（静默模式）；不可达时回退本地 task_pool。
    注意：操控席本地编辑后的 plan 优先于数据服务器缓存，避免 PATCH 后被旧数据覆盖。"""
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    # 1) 优先检查本地 task_pool 是否已有该 plan（操控席本地编辑过）
    local_plan = task_pool.get(rid)

    data = _http_get_operator(f"/api/v1/task_pool/resources/simple/{rid}", silent=True)
    if data is not None and isinstance(data, dict):
        remote_plan = _normalize_plan_field_names(data)

        # 本地 plan 有未同步的修改（local_dirty）时，无条件优先使用本地版本，
        # 避免删除/编辑后 actions 数量变少，被数据服务器旧缓存覆盖。
        if local_plan and local_plan.get("local_dirty"):
            print(f"[AS-DEBUG] get_plan_detail_operator use local task_pool because local_dirty=true, plan_id={plan_id}")
            plan = local_plan
        else:
            # 比较本地和远程 plan 的 actions 数量，优先使用 actions 更完整的版本。
            # 避免数据服务器 /simple 接口投影丢失 team_actions 后覆盖本地完整假数据/编辑数据。
            def _count_actions(p):
                if not p or not isinstance(p, dict):
                    return 0
                count = 0
                for stage in p.get("stages", []) or []:
                    team_actions = stage.get("team_actions", {})
                    if isinstance(team_actions, dict):
                        for vlist in team_actions.values():
                            if isinstance(vlist, list):
                                for v in vlist:
                                    if isinstance(v, dict):
                                        count += len(v.get("actions") or [])
                    elif isinstance(team_actions, list):
                        for ta in team_actions:
                            if not isinstance(ta, dict):
                                continue
                            for v in ta.get("car_actions", []) or []:
                                if isinstance(v, dict):
                                    count += len(v.get("actions") or [])
                            for v in ta.get("team_actions", []) or []:
                                if isinstance(v, dict):
                                    count += len(v.get("actions") or [])
                return count

            local_actions = _count_actions(local_plan)
            remote_actions = _count_actions(remote_plan)

            if local_plan and local_actions >= remote_actions:
                print(f"[AS-DEBUG] get_plan_detail_operator use local task_pool (actions={local_actions} >= remote={remote_actions}), plan_id={plan_id}")
                plan = local_plan
            else:
                print(f"[AS-DEBUG] get_plan_detail_operator use remote (remote_actions={remote_actions} > local={local_actions}), plan_id={plan_id}")
                plan = remote_plan
                task_pool.set(rid, plan)
    else:
        print(f"[AS-DEBUG] get_plan_detail_operator fallback to local task_pool, plan_id={plan_id}")
        plan = local_plan

    if plan is None:
        return None

    car_actions = _build_car_actions_from_plan(plan)
    result = _to_frontend_plan(plan, car_actions)
    # 根据数据服务端中的 action 状态推断并初始化运行时状态（避免前后端不一致）
    action_runtime.init_state_from_plan(plan_id, result)
    return result


def import_plan_to_operator(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将行动方案原样 import 到操控席数据服务器"""
    result = _http_post_operator(
        "/api/v1/task_pool/ingestion/import",
        {"resources": [plan], "return_data_type": "typed", "ignore_errors": True},
    )
    return result


def create_operator_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """在本地 task_pool 创建/保存一个新的 PLAN 资源；操控席数据服务器不可达时作为兜底"""
    from app.services.task_pool import task_pool

    plan_id = plan.get("plan_id") or plan.get("resource_id", "").replace("plan:", "")
    if not plan_id:
        plan_id = f"PLAN_{uuid.uuid4().hex[:16].upper()}"
        plan["plan_id"] = plan_id

    rid = plan.get("resource_id") or f"plan:{plan_id}"
    plan["resource_id"] = rid
    plan["task_type"] = "PLAN"

    now = datetime.now(timezone.utc).isoformat()
    plan.setdefault("created_at", now)
    plan.setdefault("updated_at", now)
    plan.setdefault("search_text", f"{plan.get('title', '')} {plan.get('description', '')}")
    if "lifecycle" not in plan:
        plan["lifecycle"] = {"state": "DRAFT", "created_at": now, "updated_at": now}

    # 尝试导入数据服务器；失败或不可达则仅保存本地
    try:
        import_plan_to_operator(plan)
    except Exception:
        pass

    task_pool.set(rid, plan)
    return task_pool.get(rid)


def update_operator_plan_locally(plan_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """仅更新本地 task_pool 中的 PLAN 资源，不同步到数据服务器"""
    from app.services.task_pool import task_pool

    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"
    existing = task_pool.get(rid)
    if not existing:
        return None

    # 仅允许更新白名单字段；stages/teams/targets 可整段替换
    allowed_top_keys = {"title", "description", "state", "teams", "targets", "stages", "search_text", "car_actions", "vehicle_summary"}
    for key, value in payload.items():
        if key in allowed_top_keys:
            existing[key] = copy.deepcopy(value)

    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    # 标记本地 plan 已被修改但尚未成功同步到数据服务器
    existing["local_dirty"] = True
    task_pool.set(rid, existing)
    return task_pool.get(rid)


def sync_plan_to_operator(plan_id: str) -> bool:
    """把本地 task_pool 中的 plan 通过 ingestion/import 同步到操控席数据服务器。

    经过测试，PATCH /resources/{rid} 无法保存 stages.team_actions 等嵌套字段，
    因此改用全量 import 方式 upsert，确保行动序列数据落盘到数据服务器。
    """
    from app.services.task_pool import task_pool

    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"
    plan = task_pool.get(rid)
    if not plan:
        return False
    try:
        payload = {
            "resource_id": rid,
            "task_type": "PLAN",
            "plan_id": plan.get("plan_id") or rid.replace("plan:", ""),
            "title": plan.get("title", ""),
            "description": plan.get("description", ""),
            "state": plan.get("state") or "DRAFT",
            "teams": plan.get("teams", []),
            "targets": plan.get("targets", []),
            "stages": plan.get("stages", []),
        }
        result = _http_post_operator(
            "/api/v1/task_pool/ingestion/import",
            {"resources": [payload], "return_data_type": "typed", "ignore_errors": True},
            silent=True,
        )
        if result is None:
            return False
        # 同步成功后清除本地 dirty 标记
        synced = task_pool.get(rid)
        if synced and isinstance(synced, dict):
            synced["local_dirty"] = False
            task_pool.set(rid, synced)
        return True
    except Exception as e:
        print(f"[SYNC-PLAN] sync to operator failed: {e}")
        return False



