"""
行动序列数据服务客户端
职责：
  1. 从数据服务器获取 PLAN / STAGE / ACTION 数据
  2. 将 plan.team_actions 转换为按车辆(vid)组织的行动序列
  3. 维护行动序列的运行状态（内存）

与杀伤链的区分：
  - 杀伤链: data_server_client.py 处理 KILL_CHAIN 类型
  - 行动序列: action_sequence_client.py 处理 PLAN / STAGE / ACTION / CAR_ACTIONS 类型
"""

import copy
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.services.data_server_client import _http_get, _http_post


def _build_car_actions_from_plan(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    将 plan.stages[].team_actions 转换为按车辆(vid)组织的行动序列列表。
    兼容两种数据结构：
      - 真实服务器: team_actions 为 list[{"team_id": "...", "team_actions": [...]}]
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
                vehicles = ta.get("team_actions", [])
                team_vehicle_pairs.append((team_id, vehicles))

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
                })

    # 按 stage_seq -> vid 排序
    results.sort(key=lambda x: (x["stage_seq"], x["vid"]))
    return results


def query_plans(limit: int = 20) -> List[Dict[str, Any]]:
    """查询行动方案列表 — 直接走数据服务器"""
    data = _http_post(
        "/api/v1/task_pool/resources/query",
        {"task_type": "PLAN", "limit": limit},
    )
    if data is not None and isinstance(data, list):
        result = []
        for item in data:
            raw = item.get("raw_payload", {}) or {}
            if not isinstance(raw, dict):
                raw = {}
            # title 优先从 tactic.title -> raw_payload.title -> 顶层title -> plan_id
            tactic = raw.get("tactic") or {}
            if not isinstance(tactic, dict):
                tactic = {}
            title = (
                tactic.get("title")
                or raw.get("title")
                or item.get("title")
                or raw.get("plan_id", "")
            )
            # state 优先从 raw_payload.state -> 顶层state -> DRAFT
            state = raw.get("state") or item.get("state") or "DRAFT"
            result.append({
                "plan_id": raw.get("plan_id") or item.get("resource_id", "").replace("plan:", ""),
                "resource_id": item.get("resource_id", ""),
                "title": title,
                "description": raw.get("description") or item.get("description") or "",
                "state": state,
                "teams_count": len(raw.get("teams", [])),
                "stages_count": len(raw.get("stages", [])),
            })
        return result

    # 服务器不可达或异常 — 返回空列表
    return []


def get_plan_detail(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    获取方案详情，并转换为前端行动序列需要的格式。
    服务器不可达或不存在时返回 None（前端显示空）。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    data = _http_get(f"/api/v1/task_pool/resources/{rid}")
    if data is not None:
        raw = data.get("raw_payload", data)
        plan = raw if isinstance(raw, dict) else {}
        car_actions = _build_car_actions_from_plan(plan)
        return _to_frontend_plan(plan, car_actions)

    # 服务器不可达或 plan 不存在 — 返回 None
    return None


def _to_frontend_plan(plan: Dict[str, Any], car_actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """转换为前端需要的 Plan + ActionSequence 格式"""
    # 车辆汇总：按 vid 聚合所有阶段中的行动
    vehicle_map: Dict[str, Dict[str, Any]] = {}
    for ca in car_actions:
        vid = ca["vid"]
        if vid not in vehicle_map:
            vehicle_map[vid] = {
                "vid": vid,
                "total_actions": 0,
                "current_state": "READY",
                "stages": [],
            }
        vehicle_map[vid]["total_actions"] += len(ca.get("actions", []))
        vehicle_map[vid]["stages"].append({
            "stage_id": ca["stage_id"],
            "stage_title": ca["stage_title"],
            "stage_seq": ca["stage_seq"],
            "actions": ca.get("actions", []),
            "state": ca.get("state", "READY"),
        })

    # title fallback：tactic.title -> raw_payload.title -> plan_id
    tactic = plan.get("tactic") or {}
    if not isinstance(tactic, dict):
        tactic = {}
    title = (
        tactic.get("title")
        or plan.get("title")
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
        """尝试状态转移，返回 (success, message)"""
        if new_state not in self.VALID_STATES:
            return False, f"非法状态: {new_state}"

        self._ensure(plan_id)
        current = self._states[plan_id]["state"]
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


# 全局单例
action_runtime = ActionSequenceRuntime()
