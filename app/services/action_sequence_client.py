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

from app.services.data_server_client import _http_get, _http_post, _http_get_operator, _http_post_operator
from app.services import zenoh_client


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
    """查询行动方案列表 — 调用数据服务器 GET /by_type/PLAN（静默模式，不打印日志）"""
    data = _http_get("/api/v1/task_pool/resources/by_type/PLAN", silent=True)
    items = []
    if data is not None and isinstance(data, list):
        items = data[:limit]
    elif data is not None and isinstance(data, dict):
        # 有些接口返回 { items: [...] }
        items = (data.get("items") or data.get("data") or [])[:limit]

    result = []
    for item in items:
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


def get_plan_detail(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    获取方案详情，并转换为前端行动序列需要的格式（静默模式，不打印日志）。
    服务器不可达或不存在时返回 None（前端显示空）。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    data = _http_get(f"/api/v1/task_pool/resources/{rid}", silent=True)
    if data is not None and isinstance(data, dict):
        # 数据服务端返回的原始数据本身即包含业务字段，无需再提取 raw_payload
        plan = data
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


# ==================== Plan → MissionService mission_data 转换 ====================


def _action_name_to_sid(name: str) -> int:
    """根据 action 名称关键词推断元任务 sid"""
    if not name:
        return 1
    n = name.lower()
    if "静默" in n or "值守" in n or "驻守" in n:
        return 4
    if "返航" in n or "返回基地" in n or "回基地" in n:
        return 6
    if "人工" in n or "保障" in n:
        return 8
    if "设置返航点" in n or "返航点" in n:
        return 5
    if "跟随" in n:
        return 2
    if "编队" in n:
        return 7
    if "姿态" in n or "转向" in n:
        return 9
    # 默认：自主机动
    return 1


def _build_service_from_action(action: Dict[str, Any]) -> Dict[str, Any]:
    """将单个 action 转换为 mission_data act.service"""
    name = action.get("name", "")
    description = action.get("description", "")
    param = action.get("param") or {}
    waypoints = param.get("waypoints") if isinstance(param, dict) else None
    sid = _action_name_to_sid(name)

    # sid = 1: 自主机动 — 优先使用 waypoints
    if sid == 1 and waypoints and isinstance(waypoints, list) and len(waypoints) >= 2:
        points = []
        for wp in waypoints:
            if isinstance(wp, dict):
                points.append({
                    "lon": int(wp.get("longitude", 0) * 1e6),
                    "lat": int(wp.get("latitude", 0) * 1e6),
                    "alt": int((wp.get("altitude", 0) or 0) * 10),
                    "radius": wp.get("radius", -1),
                    "type": wp.get("type", 1),
                })
        if len(points) >= 2:
            return {
                "sid": 1,
                "points": points,
                "limited_speed": param.get("limited_speed", 20),
                "safe_mode": param.get("safe_mode", 0),
                "loop_mode": param.get("loop_mode", 0),
            }
        # waypoints 不足 2 个，fallback 到默认 sid=1（空 points 或占位）
        return {
            "sid": 1,
            "points": [
                {"lon": 116397128, "lat": 39909231, "alt": 435, "radius": -1, "type": 1},
                {"lon": 116397500, "lat": 39909500, "alt": 435, "radius": -1, "type": 1},
            ],
            "limited_speed": 20,
            "safe_mode": 0,
            "loop_mode": 0,
        }

    # sid = 1 但没有 waypoints — 用描述中的坐标或默认值
    if sid == 1:
        # 尝试从 description 提取坐标（简易正则）
        coords = re.findall(r"([\d.]+)[°\s]*([NSns])?[,\s]*([\d.]+)[°\s]*([EWew])?", description)
        points = []
        for m in coords:
            try:
                lat = float(m[0])
                lon = float(m[2])
                if m[1] and m[1].upper() == "S":
                    lat = -lat
                if m[3] and m[3].upper() == "W":
                    lon = -lon
                points.append({"lon": int(lon * 1e6), "lat": int(lat * 1e6), "alt": 435, "radius": -1, "type": 1})
            except Exception:
                pass
        if len(points) >= 2:
            return {"sid": 1, "points": points, "limited_speed": 20, "safe_mode": 0, "loop_mode": 0}
        # 默认占位点
        return {
            "sid": 1,
            "points": [
                {"lon": 116397128, "lat": 39909231, "alt": 435, "radius": -1, "type": 1},
                {"lon": 116397500, "lat": 39909500, "alt": 435, "radius": -1, "type": 1},
            ],
            "limited_speed": 20,
            "safe_mode": 0,
            "loop_mode": 0,
        }

    if sid == 4:
        return {"sid": 4, "time": param.get("time", 20)}

    if sid == 5:
        return {"sid": 5}

    if sid == 6:
        return {"sid": 6}

    if sid == 2:
        return {
            "sid": 2,
            "x": param.get("x", 960),
            "y": param.get("y", 540),
            "width": param.get("width", 1920),
            "height": param.get("height", 1080),
            "limited_speed": param.get("limited_speed", 15),
            "safe_mode": param.get("safe_mode", 0),
            "strategy": param.get("strategy", 0),
        }

    if sid == 7:
        return {
            "sid": 7,
            "points": param.get("points", []),
            "limited_speed": param.get("limited_speed", 20),
            "formation_mode": param.get("formation_mode", 0),
            "safe_mode": param.get("safe_mode", 0),
        }

    if sid == 9:
        return {
            "sid": 9,
            "pose": param.get("pose", [9000, 0, 0]),
            "pose_deviation": param.get("pose_deviation", [100, 100, 100]),
            "limited_speed": param.get("limited_speed", 10),
            "safe_mode": param.get("safe_mode", 0),
        }

    if sid == 8:
        return {"sid": 8, "type": param.get("type", 1)}

    # 兜底
    return {"sid": 1, "points": [], "limited_speed": 20, "safe_mode": 0, "loop_mode": 0}


def build_mission_data(
    plan: Dict[str, Any],
    vehicle_vmfs: Optional[Dict[str, int]] = None,
    vehicle_ips: Optional[Dict[str, str]] = None,
    tid: Optional[int] = None,
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
                    if vid and actions:
                        if vid not in vehicle_actions_map:
                            vehicle_actions_map[vid] = []
                        vehicle_actions_map[vid].extend(actions)
        elif isinstance(team_actions, list):
            for ta in team_actions:
                team_id = ta.get("team_id", "")
                vehicles = ta.get("team_actions", [])
                for vehicle in vehicles:
                    vid = vehicle.get("vid", "")
                    actions = vehicle.get("actions", [])
                    if vid and actions:
                        if vid not in vehicle_actions_map:
                            vehicle_actions_map[vid] = []
                        vehicle_actions_map[vid].extend(actions)

    # 也兼容 vehicle_summary 结构
    vehicle_summary = plan.get("vehicle_summary", [])
    for vsum in vehicle_summary:
        vid = vsum.get("vid", "")
        for stage in vsum.get("stages", []):
            actions = stage.get("actions", [])
            if vid and actions:
                if vid not in vehicle_actions_map:
                    vehicle_actions_map[vid] = []
                vehicle_actions_map[vid].extend(actions)

    # 去重并排序（按 action_seq）
    for vid in vehicle_actions_map:
        seen = set()
        uniq = []
        for a in vehicle_actions_map[vid]:
            aid = a.get("action_id", a.get("action_seq", id(a)))
            if aid not in seen:
                seen.add(aid)
                uniq.append(a)
        uniq.sort(key=lambda x: x.get("action_seq", 0))
        vehicle_actions_map[vid] = uniq

    # 构建 vehicles
    mission_vehicles = []
    for vid, actions in vehicle_actions_map.items():
        vmf = (vehicle_vmfs or {}).get(vid)
        if vmf is None:
            # 尝试 vid 本身就是数字
            try:
                vmf = int(vid)
            except (ValueError, TypeError):
                vmf = 99076716  # 兜底：ZD04 的示例 vmf

        vip = (vehicle_ips or {}).get(vid, "192.168.1.11")
        num = len(actions)

        acts = []
        for idx, action in enumerate(actions, start=1):
            service = _build_service_from_action(action)
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
) -> Dict[str, Any]:
    """
    构建完整的 MissionService send_mission payload。

    Returns:
        {"service": "MissionService", "action": "send_mission", "args": {"mission_data": {...}}}
    """
    mission_data = build_mission_data(plan, vehicle_vmfs, vehicle_ips, tid)
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
    return "ZD04"


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
        vid = get_first_vid(plan) if plan else "ZD04"

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


# ==================== 操控席数据服务端接口 ====================


def query_plans_operator(limit: int = 20) -> List[Dict[str, Any]]:
    """向操控席数据服务器查询行动方案列表 — GET /by_type/PLAN（静默模式）"""
    data = _http_get_operator("/api/v1/task_pool/resources/by_type/PLAN", silent=True)
    items = []
    if data is not None and isinstance(data, list):
        items = data[:limit]
    elif data is not None and isinstance(data, dict):
        items = (data.get("items") or data.get("data") or [])[:limit]

    result = []
    for item in items:
        raw = item.get("raw_payload", {}) or {}
        if not isinstance(raw, dict):
            raw = {}
        tactic = raw.get("tactic") or {}
        if not isinstance(tactic, dict):
            tactic = {}
        title = (
            tactic.get("title")
            or raw.get("title")
            or item.get("title")
            or raw.get("plan_id", "")
        )
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


def get_plan_detail_operator(plan_id: str) -> Optional[Dict[str, Any]]:
    """向操控席数据服务器获取方案详情（静默模式）"""
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"
    data = _http_get_operator(f"/api/v1/task_pool/resources/{rid}", silent=True)
    if data is not None and isinstance(data, dict):
        plan = data
        car_actions = _build_car_actions_from_plan(plan)
        return _to_frontend_plan(plan, car_actions)
    return None


def import_plan_to_operator(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将行动方案原样 import 到操控席数据服务器"""
    result = _http_post_operator(
        "/api/v1/task_pool/ingestion/import",
        {"resources": [plan], "return_data_type": "typed", "ignore_errors": True},
    )
    return result
