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
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from app.config import FORMATION_MISSION_SEND_URL
from app.services.data_server_client import (
    _http_get, _http_post, _http_patch,
    _http_get_operator, _http_post_operator, _http_patch_operator,
    _http_get_resource_pool,
    forward_resources_to_targets,
)
from app.services.task_pool import task_pool
from app.services import zenoh_client
from app.services import vehicle_control_client
from app.services.sse_manager import sse_manager


def _infer_resource_type_from_vid(vid: str) -> str:
    """从 equipment vid 推断 resource_type，用于数据服务器 team_equipments 为空时的兜底。

    支持真实装备编号前缀：
      ZD/Recon-Strike-UGV, XL/Patrol-UGV, HL/Fire-Support-UGV,
      DC/Electronic-UGV, DD/Electronic-UGV(兼容), KD/Air-Ground-UAV,
      CK/Remote-Control-Car(远程操控车)
    """
    v = (vid or "").lower()
    # 真实装备编号前缀
    if re.search(r"(^|[:_-])ck\d", v):
        return "Remote-Control-Car"
    if re.search(r"(^|[:_-])zd\d", v):
        return "Recon-Strike-UGV"
    if re.search(r"(^|[:_-])xl\d", v):
        return "Patrol-UGV"
    if re.search(r"(^|[:_-])hl\d", v):
        return "Fire-Support-UGV"
    if re.search(r"(^|[:_-])dc\d", v):
        return "Electronic-UGV"
    if re.search(r"(^|[:_-])dd\d", v):
        return "Electronic-UGV"
    if re.search(r"(^|[:_-])kd\d", v):
        return "Air-Ground-UAV"
    # 英文描述前缀兜底
    if "fire-support" in v:
        return "Fire-Support-UGV"
    if "recon-strike" in v:
        return "Recon-Strike-UGV"
    if "patrol" in v:
        return "Patrol-UGV"
    if "electronic" in v:
        return "Electronic-UGV"
    if "air-ground" in v:
        return "Air-Ground-UAV"
    return ""


def _build_car_actions_from_plan(
    plan: Dict[str, Any],
    http_post=_http_post,
) -> List[Dict[str, Any]]:
    """
    将 plan.stages[].team_actions 转换为按车辆(vid)组织的行动序列列表。
    兼容三种数据结构：
      - 数据服务器标准 /simple: team_actions 为 list[{"team_id": "...", "car_actions": [...]}]
      - 旧真实服务器: team_actions 为 list[{"team_id": "...", "team_actions": [...]}]
      - 旧 Mock 数据: team_actions 为 dict{"team_id": [...]}
    当 plan.stages[].team_actions 中引用的 vehicle 的 actions 为空（数据服务器 /simple 投影丢失）时，
    按 car_actions_id 精确匹配从数据服务器查询 CAR_ACTIONS 资源补全该引用的 actions。
    不做整 plan 级别的反查补全：stages 未引用的车辆/行动一律不显示。

    http_post 参数用于指定调用哪个数据服务器：默认 _http_post（协同席数据服务器），
    操控席调用时应传入 _http_post_operator，避免席位数据串用。
    """
    plan_id = plan.get("plan_id", "")
    stages = plan.get("stages", [])
    results: List[Dict[str, Any]] = []

    # 先按 stages.team_actions 收集，同时记录需要补全的 (stage_id, vid)
    missing_queries = []
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
                ca_id = vehicle.get("car_actions_id") or f"ca:{plan_id}:{stage_id}:{vid}"
                # 如果该 vehicle 的 actions 为空，标记后续从 CAR_ACTIONS 补全
                if vid and not actions:
                    missing_queries.append((stage_id, stage_seq, stage_title, team_id, vid, ca_id, vehicle.get("action_ids") or []))
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

    # 注意：不做整 plan 级别的 CAR_ACTIONS 反查补全——前端显示必须与 plan 文档严格一致，
    # stages 中没有引用的车辆/行动（数据服务器上的历史残留）不显示。

    # 按 plan_id 查询 CAR_ACTIONS / ACTION 资源补全 actions（按 car_actions_id 精确匹配，避免跨阶段串用）
    if missing_queries:
        try:
            print(f"[AS-DEBUG] _build_car_actions_from_plan try to query CAR_ACTIONS for plan_id={plan_id}, missing_vids={[q[4] for q in missing_queries]}")
            car_actions_data = http_post(
                "/api/v1/task_pool/resources/query",
                {"task_type": "CAR_ACTIONS", "limit": 200, "filters": {"plan_id": plan_id}},
                silent=False,
                timeout=(1, 5),
            )
            print(f"[AS-DEBUG] CAR_ACTIONS query returned type={type(car_actions_data)}, len={len(car_actions_data) if isinstance(car_actions_data, list) else 'N/A'}")
            if isinstance(car_actions_data, list):
                # 建立 car_actions_id -> actions / action_ids 映射，按资源精确匹配而不是按 vid 汇总
                ca_id_to_actions = {}
                ca_id_to_action_ids = {}
                for ca in car_actions_data:
                    ca_id = ca.get("car_actions_id", "")
                    if not ca_id:
                        continue
                    ca_actions = ca.get("actions", [])
                    ca_action_ids = ca.get("action_ids", [])
                    print(f"[AS-DEBUG] CAR_ACTIONS item ca_id={ca_id}, vid={ca.get('vid')}, actions_len={len(ca_actions)}, action_ids_len={len(ca_action_ids)}")
                    if ca_actions:
                        ca_id_to_actions[ca_id] = ca_actions
                    if ca_action_ids:
                        ca_id_to_action_ids[ca_id] = ca_action_ids

                # 收集所有需要查询 ACTION 的 action_ids（CAR_ACTIONS 中 actions 为空但 action_ids 非空的）
                needed_action_ids = set()
                for _, _, _, _, _, ca_id, action_ids in missing_queries:
                    if ca_id not in ca_id_to_actions and ca_id in ca_id_to_action_ids:
                        needed_action_ids.update(ca_id_to_action_ids[ca_id])
                    elif ca_id not in ca_id_to_actions and action_ids:
                        needed_action_ids.update(action_ids)

                action_by_id = {}
                if needed_action_ids:
                    action_resources = http_post(
                        "/api/v1/task_pool/resources/query",
                        {"task_type": "ACTION", "limit": 500, "filters": {"plan_id": plan_id}},
                        silent=False,
                        timeout=(1, 10),
                    )
                    print(f"[AS-DEBUG] ACTION query returned type={type(action_resources)}, len={len(action_resources) if isinstance(action_resources, list) else 'N/A'}")
                    if isinstance(action_resources, list):
                        for a in action_resources:
                            aid = a.get("action_id")
                            if aid:
                                action_by_id[aid] = a

                # 按每个 (stage_id, vid) 对应的 car_actions_id 精确补全
                for item in results:
                    if item.get("actions"):
                        continue
                    ca_id = item.get("car_actions_id")
                    if not ca_id:
                        continue
                    filled = ca_id_to_actions.get(ca_id)
                    if not filled:
                        # CAR_ACTIONS 中 actions 为空，按 action_ids 从 ACTION 资源补全
                        ids = ca_id_to_action_ids.get(ca_id, [])
                        if not ids:
                            # 从 missing_queries 中拿到原始 action_ids
                            for mq in missing_queries:
                                if mq[5] == ca_id and mq[6]:
                                    ids = mq[6]
                                    break
                        if ids:
                            matched = [action_by_id[aid] for aid in ids if aid in action_by_id]
                            if matched:
                                matched.sort(key=lambda x: x.get("action_seq") or 0)
                                filled = matched
                    if filled:
                        # DS 的 CAR_ACTIONS.action_ids 是累加语义（历史重复写入会攒下多份
                        # 相同 action_id），补全时按 action_id 去重，保序保留首个
                        seen_action_ids = set()
                        deduped = []
                        for a in filled:
                            aid = a.get("action_id")
                            if aid:
                                if aid in seen_action_ids:
                                    continue
                                seen_action_ids.add(aid)
                            deduped.append(a)
                        item["actions"] = _normalize_plan_field_names(_scale_coords_to_float(deduped))
                        print(f"[AS-DEBUG] filled actions for ca_id={ca_id} vid={item.get('vid')} stage={item.get('stage_id')}, len={len(item['actions'])}")
        except Exception as e:
            print(f"[AS-DEBUG] query CAR_ACTIONS failed: {e}")
            pass

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


def _to_ds_native_field_names(obj: Any) -> Any:
    """写回数据服务器前，把本地/前端命名转为 DS 原生命名（_normalize_plan_field_names 的逆方向）。

    DS 的 TEAM 类型只认 team_name/team_description/team_equipments，ACTION 只认
    action_name/action_description；用本地命名（name/vehicles）import 时 DS 会生成
    默认名（编组-XXX / 行动-action-XXXX）并丢掉 team_equipments（2026-09-07 踩坑）。
    幂等：DS 原生键已存在时以原生键为准，本地键保留不动（DS 会忽略）。
    类型按字典形状判定：含 action_id/action_seq 视为 ACTION；
    含 team_id 且不含 actions/car_actions 视为 TEAM。
    """
    if isinstance(obj, list):
        return [_to_ds_native_field_names(item) for item in obj]
    if not isinstance(obj, dict):
        return obj

    out = {k: _to_ds_native_field_names(v) for k, v in obj.items()}

    if "action_id" in out or "action_seq" in out:
        if "action_name" not in out and "name" in out:
            out["action_name"] = out["name"]
        if "action_description" not in out and "description" in out:
            out["action_description"] = out["description"]
    elif "team_id" in out and "actions" not in out and "car_actions" not in out:
        if "team_name" not in out and "name" in out:
            out["team_name"] = out["name"]
        if "team_description" not in out and "description" in out:
            out["team_description"] = out["description"]
        if "team_equipments" not in out and "vehicles" in out:
            out["team_equipments"] = out["vehicles"]
    return out


def _plan_sort_key(item: Dict[str, Any]) -> Tuple[int, str]:
    """按 plan_id 末尾数字升序排序；无数字的排最后，并按原字符串稳定排序。"""
    plan_id = item.get("plan_id") or item.get("resource_id", "").replace("plan:", "") or ""
    match = re.search(r"(\d+)$", plan_id)
    if match:
        return (0, int(match.group(1)))
    return (1, plan_id)


# ---------- action 时间参数默认值 ----------


def _parse_duration_to_seconds(value: Any) -> int:
    """把 HH:MM:SS、MM:SS 或秒数解析为整数秒；解析失败返回 0。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), int(float(parts[2]))
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = int(parts[0]), int(float(parts[1]))
            return m * 60 + s
        return int(float(text))
    except (ValueError, TypeError):
        return 0


def _format_duration(seconds: int) -> str:
    """把秒数格式化为 HH:MM:SS。"""
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _parse_start_time(value: Any) -> Optional[datetime]:
    """解析时间字符串为 aware datetime；失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts >= 1_000_000_000:
            try:
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                return None
        return None
    fmts = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _format_start_time(dt: datetime) -> str:
    """把 datetime 格式化为带时区的 ISO 字符串。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _collect_vehicles_from_team_actions(team_actions: Any) -> List[Dict[str, Any]]:
    """统一提取 stage.team_actions 中的车辆列表。"""
    vehicles: List[Dict[str, Any]] = []
    if isinstance(team_actions, dict):
        for vlist in team_actions.values():
            if isinstance(vlist, list):
                vehicles.extend(vlist)
    elif isinstance(team_actions, list):
        for ta in team_actions:
            if not isinstance(ta, dict):
                continue
            vehicles.extend(ta.get("car_actions", []) or [])
            vehicles.extend(ta.get("team_actions", []) or [])
            if ta.get("vid") and ta.get("actions") is not None:
                vehicles.append(ta)
    return vehicles


def _normalize_action_timing(plan: Dict[str, Any]) -> None:
    """
    确保每个 action 的 start_time / mission_duration 不为 0。

    - 没有前序任务（同一车辆的首个 action）：start_time 取 plan 创建时间，mission_duration 默认 10 秒。
    - 有前序任务：start_time = 前序任务 start_time + 前序任务 mission_duration。
    - 已有有效值时保持不动；仅对缺失或 0 值进行填充。
    """
    if not isinstance(plan, dict):
        return

    base_time = _parse_start_time(plan.get("created_at") or plan.get("updated_at"))
    if base_time is None:
        base_time = datetime.now(timezone.utc)

    # 按车辆聚合所有 action，key = (stage_seq, action_seq)
    vehicle_actions: Dict[str, List[Tuple[int, int, Dict[str, Any]]]] = {}
    for stage in plan.get("stages", []) or []:
        if not isinstance(stage, dict):
            continue
        stage_seq = stage.get("stage_seq", 0) or 0
        for vehicle in _collect_vehicles_from_team_actions(stage.get("team_actions")):
            if not isinstance(vehicle, dict):
                continue
            vid = str(vehicle.get("vid", ""))
            if not vid:
                continue
            for action in vehicle.get("actions", []) or []:
                if not isinstance(action, dict):
                    continue
                action_seq = action.get("action_seq", 0) or 0
                vehicle_actions.setdefault(vid, []).append((stage_seq, action_seq, action))

    for vid, items in vehicle_actions.items():
        items.sort(key=lambda x: (x[0], x[1]))
        prev_end: Optional[datetime] = None
        for stage_seq, action_seq, action in items:
            param = action.setdefault("param", {})
            if not isinstance(param, dict):
                continue

            # mission_duration：缺失或为 0 时默认 10 秒
            duration_sec = _parse_duration_to_seconds(param.get("mission_duration"))
            if duration_sec <= 0:
                duration_sec = 10
            param["mission_duration"] = _format_duration(duration_sec)

            # start_time：缺失或为 0 时基于前序任务推导
            start_dt = _parse_start_time(param.get("start_time"))
            if start_dt is None:
                start_dt = prev_end if prev_end is not None else base_time
            param["start_time"] = _format_start_time(start_dt)
            param["enable_start_time"] = True

            prev_end = start_dt + timedelta(seconds=duration_sec)


def query_plans(limit: int = 200) -> List[Dict[str, Any]]:
    """查询行动方案列表 — 调用数据服务器 POST /resources/query。
    任务列表直接从数据服务器拉取，不使用本地缓存/假数据。"""
    data = _http_post(
        "/api/v1/task_pool/resources/query",
        {"task_type": "PLAN", "limit": limit},
        silent=False,
        timeout=(1, 10),
    )
    items = []
    if data is not None and isinstance(data, list):
        items = data[:limit]
    elif data is not None and isinstance(data, dict):
        # /retrieval/query 返回 { items: [...] }
        items = (data.get("items") or data.get("data") or [])[:limit]

    items.sort(key=_plan_sort_key)

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
            "vehicle_summary": _build_vehicle_summary_brief(item),
        })
    return result


def _build_vehicle_summary_brief(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """列表接口用的轻量 vehicle_summary：仅 vid + resource_type。

    复用详情接口的同一套车型判定（teams > 在线车辆缓存 > vid 前缀 > action_type），
    供前端按车型过滤，避免对每个 plan 再拉一次详情（N+1）。
    """
    car_actions = _build_car_actions_from_plan(plan)
    full = _to_frontend_plan(plan, car_actions)
    return [
        {"vid": v.get("vid", ""), "resource_type": v.get("resource_type", "")}
        for v in full.get("vehicle_summary", [])
    ]


def get_plan_detail(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    获取方案详情，并转换为前端行动序列需要的格式（静默模式，不打印日志）。
    数据服务器不可达时回退到本地 task_pool；本地也没有时返回 None。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    data = _http_get(f"/api/v1/task_pool/resources/simple/{rid}", silent=False)
    if data is None or not isinstance(data, dict):
        print(f"[AS-DEBUG] plan={plan_id} not found in data_server")
        return None

    # 数据服务端 /simple 接口返回的是业务字段（已做字段投影）
    plan = _normalize_plan_field_names(data)
    plan = _scale_coords_to_float(plan)

    # 本地缓存中的坐标已为浮点，确保反缩放（对浮点无影响）
    plan = _scale_coords_to_float(plan)

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


def _parse_mission_strategy(param: Dict[str, Any]) -> int:
    """从 action.param 中解析断连策略，映射为 MissionService 协议值。

    协调卡协议：0=停车；1=一键返航；2=继续任务。
    前端保存时使用同样的数字语义（continue:2, stop:0, return:1），
    因此 param.disconnect_strategy 若为合法数字可直接使用。
    """
    raw = param.get("disconnect_strategy") if isinstance(param, dict) else None
    if isinstance(raw, int) and raw in (0, 1, 2):
        return raw
    if isinstance(raw, str):
        if raw.isdigit() and int(raw) in (0, 1, 2):
            return int(raw)
        mapping = {"stop": 0, "return": 1, "continue": 2}
        if raw in mapping:
            return mapping[raw]
    return 2  # 默认继续任务


def _parse_mission_start_end(param: Dict[str, Any], default_start: str, default_end: str) -> Tuple[str, str]:
    """从 action.param 中解析开始时间和结束时间。

    仅在 enable_start_time 为真、start_time 有效且 mission_duration 不为零时，
    才返回有效的时间字符串；否则返回空字符串，build_mission_data 中会跳过
    start/end 字段，避免下发默认值。

    时间格式：前端保存为 ISO 格式或 "YYYY/MM/DD HH:mm"，统一输出为
    "YYYY-MM-DD HH:MM:SS"。
    """
    if not isinstance(param, dict):
        return "", ""

    enable = param.get("enable_start_time", False)
    start_time = param.get("start_time", "")
    duration = param.get("mission_duration", "") or "00:00:00"

    if not enable or not start_time:
        return "", ""

    # 尝试解析开始时间
    dt = None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            dt = datetime.strptime(str(start_time), fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return "", ""

    # 解析 mission_duration "HH:MM:SS"
    try:
        parts = str(duration).split(":")
        if len(parts) == 3:
            hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            hours, minutes, seconds = 0, int(parts[0]), int(parts[1])
        else:
            hours = minutes = seconds = 0
    except (ValueError, TypeError):
        hours = minutes = seconds = 0

    # 未设置任务时长时不下发 start/end
    if hours == 0 and minutes == 0 and seconds == 0:
        return "", ""

    end_dt = dt + timedelta(hours=hours, minutes=minutes, seconds=seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S")


# 标准 action_type 集合，用于判断一个字符串是否为已归一化的标准类型
_STANDARD_ACTION_TYPES = {
    "auto-move", "follow-move", "silent-guard", "set-return-point", "return-to-base",
    "formation-move", "manual-task", "pose-adjust", "air-recon", "lens-recon",
    "recon-and-strike", "30mm-gun-strike", "at-missile-strike",
    "machine-gun-strike", "rocket-strike", "loitering-munition-strike",
    "laser-illumination", "sound-expel", "acoustic-deterrence", "light-expel",
    "light-deterrence", "em-recon", "electronic-recon", "recon-and-interfere",
    "em-interference", "electronic-jamming", "payload-silent",
}


def _is_standard_action_type(action_type: str) -> bool:
    """判断 action_type 是否已为标准命名（小写连字符形式）。"""
    if not action_type:
        return False
    return action_type.strip().lower() in _STANDARD_ACTION_TYPES


def _infer_action_type_from_action_id(action_id: str) -> str:
    """当 action_type 为空或 Unknown 时，根据 action_id 推断标准 action_type。

    兼容两种 id 风格：
      - 标准语义化 id（如 auto-move / return-to-base）
      - 项目实际数据服务器 id 前缀（如 CH_RETURN / FS_LENS / RS_40MM）
    无法识别时返回空字符串，便于后续按 name/param 继续推断。
    """
    aid = (action_id or "").strip().lower().replace("_", "-")
    if not aid:
        return ""
    # 常见 action_id -> action_type 映射
    mapping = {
        # 标准语义化 id
        "auto-move": "auto-move",
        "follow-move": "follow-move",
        "formation-move": "formation-move",
        "silent-guard": "silent-guard",
        "set-return-point": "set-return-point",
        "return-to-base": "return-to-base",
        "manual-task": "manual-task",
        "pose-adjust": "pose-adjust",
        "air-recon": "air-recon",
        "lens-recon": "lens-recon",
        # 旧命名别名（装备行动序列知识-0912 MIGRATION）：shoot/launch 统一为 strike，
        # 旧 key 仅作为读取别名归一到新规范名
        "search-and-shoot": "recon-and-strike",
        "recon-strike": "recon-and-strike",
        "recon-and-strike": "recon-and-strike",
        "30mm-gun-launch": "30mm-gun-strike",
        "40mm-gun-launch": "30mm-gun-strike",
        "30mm-gun-strike": "30mm-gun-strike",
        "at-missile-launch": "at-missile-strike",
        "at-missile-strike": "at-missile-strike",
        "gun-shot": "machine-gun-strike",
        "7.62mm-gun-shot": "machine-gun-strike",
        "machine-gun-strike": "machine-gun-strike",
        "rocket-launch": "rocket-strike",
        "rocket-strike": "rocket-strike",
        "loitering-munition-launch": "loitering-munition-strike",
        "loitering-munition-strike": "loitering-munition-strike",
        "laser-illumination": "laser-illumination",
        "sound-expel": "sound-expel",
        "acoustic-deterrence": "sound-expel",
        "light-expel": "light-expel",
        "light-deterrence": "light-expel",
        "em-recon": "em-recon",
        "electronic-recon": "em-recon",
        "em-assault": "recon-and-interfere",
        "electronic-assault": "recon-and-interfere",
        "recon-and-interfere": "recon-and-interfere",
        "em-interference": "em-interference",
        "electronic-jamming": "em-interference",
        "payload-silent": "payload-silent",
        # 项目实际数据服务器 action_id 前缀（底盘类）
        "ch-move": "auto-move",
        "ch-follow": "follow-move",
        "ch-silent": "silent-guard",
        "ch-set-return": "set-return-point",
        "ch-return": "return-to-base",
        "ch-formation": "formation-move",
        "ch-manual": "manual-task",
        "ch-pose": "pose-adjust",
        # 火力车
        "fs-lens": "lens-recon",
        "fs-recon-strike": "recon-and-strike",
        "fs-gun": "machine-gun-strike",
        "fs-rocket": "rocket-strike",
        "fs-loiter": "loitering-munition-strike",
        # 侦打车
        "rs-lens": "lens-recon",
        "rs-recon-strike": "recon-and-strike",
        "rs-30mm": "30mm-gun-strike",
        "rs-40mm": "30mm-gun-strike",
        "rs-at": "at-missile-strike",
        "rs-gun": "machine-gun-strike",
        "rs-laser": "laser-illumination",
        # 巡逻车
        "pt-lens": "lens-recon",
        "pt-recon-strike": "recon-and-strike",
        "pt-gun": "machine-gun-strike",
        "pt-acoustic": "sound-expel",
        "pt-light": "light-expel",
        # 空地车 / 电磁车
        "ag-air-recon": "air-recon",
        "el-recon": "em-recon",
        "el-assault": "recon-and-interfere",
        "el-jam": "em-interference",
        "el-silent": "payload-silent",
    }
    return mapping.get(aid, "")


def _is_generic_action_id(action_id: str) -> bool:
    """判断 action_id 是否为数据服务器分配的通用编号（如 action-0063）。"""
    if not action_id:
        return True
    aid = str(action_id).strip().lower()
    # 语义化 action_id 通常包含 '-' 且以动作类型命名；通用编号形如 action-{数字}
    if aid.startswith("action-") and len(aid) > len("action-") and aid[len("action-"):].isdigit():
        return True
    return False


def _infer_action_type_from_param(param: Optional[Dict[str, Any]]) -> str:
    """当 action_type 为空且 action_id 为通用编号时，根据 param 结构推断 action_type。"""
    if not param or not isinstance(param, dict):
        return ""
    p = param

    # 激光照射：参数里有 ene/freq/meat 等字段
    if any(k in p for k in ("ene", "freq", "meat")):
        return "laser-illumination"

    # 空中侦察：空地车特有字段（service.points1/2/3 数组或旧格式顶层 points，
    # 点内含 camera/speed/gimpitch 等飞行字段）
    svc = p.get("service") if isinstance(p.get("service"), dict) else {}
    candidates = []
    for pt_list in [p.get("points")] + [svc.get(f"points{i}") for i in (1, 2, 3)]:
        if isinstance(pt_list, list) and pt_list:
            candidates.append(pt_list[0])
    if any(
        isinstance(pt, dict) and any(k in pt for k in ("camera", "speed", "gimpitch", "gimyaw", "playaw", "zoom", "loiter"))
        for pt in candidates
    ):
        return "air-recon"

    # 强声/强光拒止：有 area 且 attr 字段
    if "area" in p and "attr" in p:
        if "thr" in p and p.get("dam") == 0:
            return "sound-expel" if p.get("ammo") == 0 else "light-expel"

    # 电磁侦察 / 电磁突击 / 电磁干扰
    # 区分依据：sort=0 为突击，sort=1 为干扰；无 sort 时按 protect 兜底为干扰
    if "frequency" in p:
        if p.get("sort") == 0:
            return "recon-and-interfere"
        if p.get("sort") == 1 or "protect" in p:
            return "em-interference"
        return "em-recon"

    # 载荷静默
    if set(p.keys()) <= {"time"}:
        return "payload-silent"

    # 设置返航点：空参数
    if not p:
        return ""

    # 开启返航：依赖字段或空参数（与设置返航点区分度低，优先按名称推断）

    # 打击类：points 数组
    if "points" in p and isinstance(p["points"], list) and len(p["points"]) > 0:
        first = p["points"][0]
        if isinstance(first, dict):
            # 30炮：tart=6, attr=1, thr=80, dam=1, blk=2, figt=2, sug=3
            if first.get("tart") == 6 and first.get("attr") == 1:
                # 30炮与机枪、火箭弹、巡飞弹参数结构相似，按 sort/num 区分度低
                # 但可通过 ammo_type 区分：30炮 ammo_type=2，机枪 ammo_type=1
                ammo_type = first.get("ammo_type")
                if ammo_type == 2:
                    return "30mm-gun-strike"
                if ammo_type == 1:
                    return "machine-gun-strike"
                # 无 ammo_type 时无法精确区分，保留空字符串让前端兜底
                return ""
            # 红箭13导弹：通常有 tart/attr 但 ammo_type 不同
            if "ammo_type" in first:
                return "at-missile-strike"
            # 火箭弹：通常 points 里有 r 字段
            if "r" in first or p.get("type") == 2:
                return "rocket-strike"
            # 巡飞弹：通常有 loiter 相关字段
            if "loiter" in p or p.get("type") == 3:
                return "loitering-munition-strike"

    # 光电侦察：area + direct
    if "area" in p and "direct" in p:
        return "lens-recon"

    # 侦察打击：area 但没有 direct（与 lens-recon 区分）
    if "area" in p:
        return "recon-and-strike"

    # 编队机动：points + formation_mode，或路径点带 offsetX/offsetY
    if "points" in p and "formation_mode" in p:
        return "formation-move"
    if (
        "points" in p
        and isinstance(p.get("points"), list)
        and len(p["points"]) > 0
        and any(isinstance(pt, dict) and ("offsetX" in pt or "offsetY" in pt) for pt in p["points"])
    ):
        return "formation-move"

    # 自主机动：points + limited_speed（且不含 formation_mode/offsetX/offsetY，避免与编队机动混淆）
    if "points" in p and "limited_speed" in p and "formation_mode" not in p:
        return "auto-move"

    # 跟随机动：x, y, distance
    if "distance" in p and "x" in p and "y" in p:
        return "follow-move"

    # 静默值守：time
    if "time" in p and len(p) == 1:
        return "silent-guard"

    # 人工任务：type 单一字段
    if "type" in p and len(p) == 1:
        return "manual-task"

    # 姿态调整：pose
    if "pose" in p:
        return "pose-adjust"

    return ""


def _infer_action_type_from_name(name: str) -> str:
    """当 action_type 为空且 action_id/param 都无法推断时，根据 name 推断。

    同时兼容中文名称与 PascalCase / 小写无连字符的英文名称，方便处理数据服务器
    中只返回英文 name 或 name 被误写的情况。
    """
    if not name:
        return ""
    n = str(name).strip()
    # 先按原始名称精确匹配（中文优先）
    mapping = {
        # 中文
        "自主机动": "auto-move",
        "跟随机动": "follow-move",
        "静默值守": "silent-guard",
        "设置返航点": "set-return-point",
        "开启返航": "return-to-base",
        "编队机动": "formation-move",
        "人工任务": "manual-task",
        "姿态调整": "pose-adjust",
        "空中侦察": "air-recon",
        "光电侦察": "lens-recon",
        "侦察打击": "recon-and-strike",
        "巡逻车侦察打击": "recon-and-strike",
        "30炮打击": "30mm-gun-strike",
        "40炮打击": "30mm-gun-strike",
        "红箭13导弹打击": "at-missile-strike",
        "机枪打击": "machine-gun-strike",
        "火箭弹打击": "rocket-strike",
        "巡飞弹打击": "loitering-munition-strike",
        "激光照射": "laser-illumination",
        "强声拒止": "sound-expel",
        "强光拒止": "light-expel",
        "电磁侦察": "em-recon",
        "电磁突击": "recon-and-interfere",
        "侦察干扰": "recon-and-interfere",
        "电磁干扰": "em-interference",
        "载荷静默": "payload-silent",
    }
    if n in mapping:
        return mapping[n]
    # 英文名称兜底：忽略大小写与连字符
    n_norm = n.lower().replace("-", "").replace("_", "").replace(".", "")
    en_mapping = {
        "automove": "auto-move",
        "followmove": "follow-move",
        "silentguard": "silent-guard",
        "setreturnpoint": "set-return-point",
        "setreturn": "set-return-point",
        "returntobase": "return-to-base",
        "return": "return-to-base",
        "formationmove": "formation-move",
        "formation": "formation-move",
        "manualtask": "manual-task",
        "manual": "manual-task",
        "poseadjust": "pose-adjust",
        "airrecon": "air-recon",
        "lensrecon": "lens-recon",
        "searchandshoot": "recon-and-strike",
        "reconstrike": "recon-and-strike",
        "reconandstrike": "recon-and-strike",
        "30mmgunlaunch": "30mm-gun-strike",
        "30mmgunstrike": "30mm-gun-strike",
        "30mmgun": "30mm-gun-strike",
        "40mmgunlaunch": "30mm-gun-strike",
        "40mmgun": "30mm-gun-strike",
        "atmissilelaunch": "at-missile-strike",
        "atmissilestrike": "at-missile-strike",
        "atmissile": "at-missile-strike",
        "gunshot": "machine-gun-strike",
        "762mmgunshot": "machine-gun-strike",
        "762mmgun": "machine-gun-strike",
        "machinegunstrike": "machine-gun-strike",
        "rocketlaunch": "rocket-strike",
        "rocketstrike": "rocket-strike",
        "loiteringmunitionlaunch": "loitering-munition-strike",
        "loiteringmunitionstrike": "loitering-munition-strike",
        "loiteringmunition": "loitering-munition-strike",
        "laserillumination": "laser-illumination",
        "laser": "laser-illumination",
        "soundexpel": "sound-expel",
        "acousticdeterrence": "sound-expel",
        "lightexpel": "light-expel",
        "lightdeterrence": "light-expel",
        "emrecon": "em-recon",
        "electronicrecon": "em-recon",
        "emassault": "recon-and-interfere",
        "electronicassault": "recon-and-interfere",
        "reconandinterfere": "recon-and-interfere",
        "eminterference": "em-interference",
        "electronicjamming": "em-interference",
        "payloadsilent": "payload-silent",
    }
    return en_mapping.get(n_norm, "")


def _infer_vehicle_type_from_action_type(action_type: str) -> str:
    """根据 action_type 推断车辆类型，用于 plan.teams 中缺少 resource_type 时的兜底。

    注意：底盘类元任务（Auto-Move 等）对所有车型通用，不能用于推断车型，
    因此这里只根据各车型特有的载荷任务进行推断。
    """
    t = (action_type or "").strip().lower()
    if not t:
        return ""
    # 火力车
    # 注意：lens-recon / recon-and-strike / machine-gun-strike 为多车型通用载荷，
    # 不能用于推断车型，否则会把侦打车/巡逻车误显示为火力车。
    if t in {"rocket-strike", "loitering-munition-strike", "gun-shot"}:
        return "Fire-Support-UGV"
    # 侦打车
    if t in {"30mm-gun-strike", "at-missile-strike"}:
        return "Recon-Strike-UGV"
    # 巡逻车
    if t in {"sound-expel", "acoustic-deterrence", "light-expel", "light-deterrence"}:
        return "Patrol-UGV"
    # 电磁车
    if t in {"em-recon", "electronic-recon", "recon-and-interfere",
             "em-interference", "electronic-jamming", "payload-silent"}:
        return "Electronic-UGV"
    # 空地车
    if t in {"air-recon", "air_recon", "ag_air_recon"}:
        return "Air-Ground-UAV"
    return ""


def _to_frontend_plan(plan: Dict[str, Any], car_actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """转换为前端需要的 Plan + ActionSequence 格式"""
    # 先建立 vid -> resource_type 映射（从 plan.teams 查找；若 teams 中 resource_type 为空，
    # 优先回退到在线车辆缓存，最后按 vid 前缀推断）
    team_type_map: Dict[str, str] = {}
    for team in plan.get("teams", []):
        if not isinstance(team, dict):
            continue
        vehicles = team.get("vehicles", [])
        team_resource_type = team.get("resource_type", "")
        for v in vehicles:
            if isinstance(v, dict) and v.get("vid"):
                vid = v["vid"]
                rt = v.get("resource_type") or team_resource_type or ""
                if not rt:
                    rt = (
                        _online_vehicle_type_cache.get(vid)
                        or _infer_resource_type_from_vid(vid)
                        or _lookup_vehicle_type_from_resource_pool(vid)
                        or ""
                    )
                team_type_map[vid] = rt
            elif isinstance(v, str):
                # 数据服务器 team_equipments 仅返回 vid 字符串时，
                # 优先查在线车辆缓存，其次根据 vid 前缀推断。
                cached = _online_vehicle_type_cache.get(v)
                team_type_map[v] = (
                    cached
                    or _infer_resource_type_from_vid(v)
                    or _lookup_vehicle_type_from_resource_pool(v)
                    or ""
                )
        if team.get("vid"):
            team_type_map[team["vid"]] = team_resource_type or team_type_map.get(team["vid"], "") or ""

    # 车辆汇总：按 vid 聚合所有阶段中的行动
    vehicle_map: Dict[str, Dict[str, Any]] = {}
    for ca in car_actions:
        vid = ca["vid"]
        if vid not in vehicle_map:
            # 车型判断优先级：plan.teams > 在线车辆缓存 > vid 前缀推断 > 资源池单查 > action_type 兜底
            resource_type = (
                team_type_map.get(vid)
                or _online_vehicle_type_cache.get(vid)
                or _infer_resource_type_from_vid(vid)
                or _lookup_vehicle_type_from_resource_pool(vid)
                or ""
            )
            vehicle_map[vid] = {
                "vid": vid,
                "resource_type": resource_type,
                "total_actions": 0,
                "current_state": "READY",
                "stages": [],
            }
        actions = ca.get("actions", [])
        car_action_type = ca.get("action_type", "")
        # 把 car_actions 的 action_type 注入到每个 action 中；
        # 若 car_action_type 为空、Unknown 或非标准命名，则依次尝试：
        # 1) action_id 语义推断；2) param 结构推断；3) name 推断。
        # 最后用 name 做一次权威校正，修复脏数据中 action_type 与 name 不一致的问题。
        normalized_actions = []
        for a in actions:
            at = car_action_type or a.get("action_type", "")
            action_id = a.get("action_id", "")
            name = a.get("name", "")

            # 先把非标准 action_type（如 CH_RETURN / Return-To-Base）归一化为标准小写形式
            if at and at.lower() not in ("unknown", "unknown_action") and not _is_standard_action_type(at):
                at = _infer_action_type_from_action_id(at) or at.lower()

            if not at or at.lower() in ("unknown", "unknown_action") or not _is_standard_action_type(at):
                inferred = ""
                if _is_generic_action_id(action_id):
                    inferred = _infer_action_type_from_param(a.get("param"))
                else:
                    inferred = _infer_action_type_from_action_id(action_id)
                if not inferred:
                    inferred = _infer_action_type_from_name(name)
                at = inferred or at

            # name 是中文业务名称，最不容易被脏数据污染，用它做最终校正
            name_inferred = _infer_action_type_from_name(name)
            if name_inferred:
                at = name_inferred

            normalized_actions.append(dict(a, action_type=at))
        actions = normalized_actions

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

    # 编队机动方案：头车（action.param.is_leader 标记）排在 vehicle_summary 第一行。
    # DS 投影会把嵌套 car_actions 按资源 id 重排，teams.vehicles 顺序在投影中丢失，
    # 顺序信息只能靠 action 业务字段携带。
    def _is_leader(vdata: Dict[str, Any]) -> bool:
        for st in vdata.get("stages", []):
            for a in st.get("actions", []):
                p = a.get("param") or {}
                if isinstance(p, dict) and p.get("is_leader"):
                    return True
        return False

    ordered_vehicles = sorted(vehicle_map.values(), key=lambda v: 0 if _is_leader(v) else 1)

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
        # uuid：编辑保存时写入 DS 的六位整数，发布时作为 send_mission 的 tid
        "uuid": plan.get("uuid"),
        "title": title,
        "description": plan.get("description", ""),
        "state": plan.get("state") or "DRAFT",
        "stages": plan.get("stages", []),
        "teams": plan.get("teams", []),
        "targets": plan.get("targets", []),
        "car_actions": car_actions,
        "vehicle_summary": ordered_vehicles,
    }


# ---------- plan 数据直读数据服务器（不依赖本地缓存） ----------

# GET /resources/{rid} 响应中属于数据服务器包装层的键，读取文档时剔除
_DS_WRAPPER_KEYS = {"attributes", "connections", "relations", "source", "raw_payload"}

# 写回数据服务器时需剥离的嵌套包装层键：DS 会为资源附加这些包装，
# 原样写回会被 DS 再包一层，导致嵌套无限加深
_DS_NESTED_WRAPPER_KEYS = {
    "attributes", "connections", "relations", "source", "raw_payload",
    "search_text", "created_at", "updated_at",
}

# 注意：dependencies 不在剥离列表中。它虽是 DS 为每个资源附加的字段，
# 但对 ACTION 资源它就是业务字段（行动依赖，如 ["1"]），且 DS 会在资源类型化投影中
# 保留该值（与包装键同级共存，无法靠结构区分）。dependencies 是扁平列表，
# 原样写回不会导致嵌套加深；剥离它会导致 sync/编辑保存后行动依赖被清空
# （2026-09-07 踩坑：点击开始后行动序列 DAG 退化为单列纵向布局）。

# 后端本地附加的内部键，不得写回数据服务器
_INTERNAL_PLAN_KEYS = {"_seat", "local_dirty"}

# 顶层派生键（后端为前端展示生成，DS 原文没有），写回前删除；
# 注意只能删顶层——stages[].team_actions[].car_actions 是 DS 原生结构，必须保留
_DERIVED_TOP_KEYS = {"car_actions", "vehicle_summary"}


def _strip_ds_wrappers(obj: Any) -> Any:
    """递归剥离 DS 包装层键与本地内部键，业务数据原样保留（含 action 的 dependencies）。"""
    if isinstance(obj, list):
        return [_strip_ds_wrappers(item) for item in obj]
    if not isinstance(obj, dict):
        return obj
    return {
        k: _strip_ds_wrappers(v)
        for k, v in obj.items()
        if k not in _DS_NESTED_WRAPPER_KEYS and k not in _INTERNAL_PLAN_KEYS
    }


def _fetch_plan_document(rid: str, http_get, label: str = "data_server", normalize: bool = False) -> Optional[Dict[str, Any]]:
    """从数据服务器读取 plan 全文档（/resources/{rid}，非 /simple 投影）。

    /simple 投影会丢失 stages.team_actions 内嵌的 actions，不能作为写回数据源。
    normalize=False（默认，写回路径）保持 DS 原始字段命名，写回时不产生命名漂移；
    normalize=True 仅供需要前端命名（title/name/vehicles）的读取路径使用。
    返回坐标还原为浮点后的 plan dict；资源不存在或服务不可达返回 None。
    """
    data = http_get(f"/api/v1/task_pool/resources/{rid}", silent=False)
    if not isinstance(data, dict) or not data.get("resource_id"):
        return None
    doc = {k: v for k, v in data.items() if k not in _DS_WRAPPER_KEYS}
    # uuid 未注册进 DS 的 PLAN schema，类型化投影不返回，仅存在于 raw_payload；
    # 写回路径若以投影为准会把它从 raw_payload 一并抹掉（sync 覆盖写踩坑），这里显式保留
    if doc.get("uuid") is None:
        raw = data.get("raw_payload")
        if isinstance(raw, dict) and raw.get("uuid") is not None:
            doc["uuid"] = raw["uuid"]
    if normalize:
        doc = _normalize_plan_field_names(doc)
    doc = _scale_coords_to_float(doc)
    return doc


def _import_plan_payload(rid: str, plan: Dict[str, Any], http_post, label: str = "data_server") -> bool:
    """把 plan 文档通过 ingestion/import 全量写回数据服务器。

    以数据服务器为准：不做字段白名单挑选、不改字段命名；仅剥离嵌套子资源的
    DS 包装层（防止往返嵌套加深）、本地内部键与顶层派生键，坐标按 DS 要求缩放为整数。
    """
    payload = _strip_ds_wrappers(copy.deepcopy(plan))
    for key in _DERIVED_TOP_KEYS:
        payload.pop(key, None)
    payload["resource_id"] = rid
    payload.setdefault("task_type", "PLAN")
    payload.setdefault("plan_id", rid.replace("plan:", ""))
    # 数据服务器要求 action.param 中的经纬高以 10^6 缩放后的整数存储
    payload = _scale_coords_to_int(payload)
    result = http_post(
        "/api/v1/task_pool/ingestion/import",
        {"resources": [payload], "return_data_type": "typed", "ignore_errors": True},
        silent=False,
    )
    return result is not None


def _cache_plan(rid: str, plan: Dict[str, Any], seat: str) -> None:
    """写入本地缓存（仅作数据服务器不可达时的兜底），并标记所属席位。"""
    from app.services.task_pool import task_pool

    plan["_seat"] = seat
    task_pool.set(rid, plan)


def _get_cached_plan_for_seat(rid: str, seat: str) -> Optional[Dict[str, Any]]:
    """读取本地缓存的 plan，仅当缓存属于指定席位时返回。

    协同席/操控席同机部署时共用进程内 task_pool 单例，key 不带席位，
    该校验防止把另一个席位的缓存当作本席位数据源（席位数据串用）。
    """
    from app.services.task_pool import task_pool

    plan = task_pool.get(rid)
    if not plan:
        return None
    cached_seat = plan.get("_seat")
    if cached_seat is not None and cached_seat != seat:
        print(f"[AS-WARN] local cache seat mismatch, ignore: rid={rid} cached={cached_seat} requested={seat}")
        return None
    return plan


def _apply_action_param_update(plan: Dict[str, Any], action_id: str, param: Dict[str, Any]) -> bool:
    """在 plan 的 stages/car_actions/vehicle_summary 中同步更新指定 action 的 param。"""
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
        # 同步更新 car_actions / vehicle_summary 中同名 action，避免多份数据不一致
        for ca in plan.get("car_actions", []) or []:
            for action in ca.get("actions", []) or []:
                if action.get("action_id") == action_id:
                    action["param"] = copy.deepcopy(param)
        for vs in plan.get("vehicle_summary", []) or []:
            for stage in vs.get("stages", []) or []:
                for action in stage.get("actions", []) or []:
                    if action.get("action_id") == action_id:
                        action["param"] = copy.deepcopy(param)
    return updated


def _update_action_param_impl(
    plan_id: str,
    action_id: str,
    param: Dict[str, Any],
    http_get,
    http_post,
    label: str,
) -> bool:
    """更新 plan 中指定 action 的 param：直读数据服务器全文档 → 修改 → import 写回。

    数据服务器不支持 PATCH 嵌套字段，因此采用全文档读改写。数据服务器不可达时
    退回同席位本地缓存编辑并标记 local_dirty，待后续 sync 补偿。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    plan = _fetch_plan_document(rid, http_get, label=label)
    if plan is None:
        plan = _get_cached_plan_for_seat(rid, label)
    if plan is None:
        return False

    updated = _apply_action_param_update(plan, action_id, param)
    if not updated:
        print(f"[AS-DEBUG] action not found: plan_id={plan_id} action_id={action_id} seat={label}")
        return False

    plan["updated_at"] = datetime.now(timezone.utc).isoformat()
    ok = _import_plan_payload(rid, plan, http_post, label=label)
    plan["local_dirty"] = not ok
    _cache_plan(rid, plan, label)
    print(f"[AS-DEBUG] updated action param: plan_id={plan_id} action_id={action_id} seat={label} import_ok={ok}")
    return True


def update_action_param(plan_id: str, action_id: str, param: Dict[str, Any]) -> bool:
    """协同席 — 更新指定 action 的 param 并写回协同席数据服务器。"""
    return _update_action_param_impl(plan_id, action_id, param, _http_get, _http_post, "data_server")


def update_operator_action_param(plan_id: str, action_id: str, param: Dict[str, Any]) -> bool:
    """操控端 — 更新指定 action 的 param 并写回操控席数据服务器。"""
    return _update_action_param_impl(
        plan_id, action_id, param, _http_get_operator, _http_post_operator, "operator"
    )


def notify_plan_map_clicked(plan_id: str, http_patch, label: str = "data_server") -> Dict[str, Any]:
    """方案条目被点击时通知数据服务器：PATCH payload.last_click，由 DS 负责后续上图。

    DS 侧处理逻辑未上线时转发会失败，仅记日志并返回 ok=False，不影响前端选中流程。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"
    last_click = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = http_patch(
        f"/api/v1/task_pool/resources/{rid}",
        {"payload": {"last_click": last_click}},
        silent=False,
    )
    if result is None:
        print(f"[MAP-NOTIFY] PATCH failed: plan_id={plan_id} seat={label}")
        return {"ok": False, "error": "patch data server failed"}
    print(f"[MAP-NOTIFY] plan_id={plan_id} seat={label} last_click={last_click}")
    return {"ok": True, "plan_id": plan_id, "last_click": last_click}


def notify_plan_map_clicked_coordinator(plan_id: str) -> Dict[str, Any]:
    """协同席 — 通知协同席数据服务器。"""
    return notify_plan_map_clicked(plan_id, _http_patch, "data_server")


def notify_plan_map_clicked_operator(plan_id: str) -> Dict[str, Any]:
    """操控席 — 通知操控席数据服务器。"""
    return notify_plan_map_clicked(plan_id, _http_patch_operator, "operator")


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
        state = copy.deepcopy(self._states[plan_id])
        state.pop("_fingerprint", None)  # 内部字段，不下发给前端
        return state

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
        以 action 状态集合为指纹：指纹不变时不覆盖（避免覆盖用户已触发的控制操作）；
        指纹变化（数据服务器上的 plan 被重写/行动状态推进）时重新推断，
        防止内存状态永久锁定在旧版本的状态（如 DONE）上。
        """
        action_states = set()
        # 从 car_actions 收集
        for ca in plan.get("car_actions", []):
            action_states.add(ca.get("state", "SCHEDULED"))
        # 从 vehicle_summary 收集
        for vs in plan.get("vehicle_summary", []):
            for stage in vs.get("stages", []):
                for action in stage.get("actions", []):
                    action_states.add(action.get("state", "SCHEDULED"))
        fingerprint = frozenset(action_states)

        existing = self._states.get(plan_id)
        if existing:
            if existing.get("_fingerprint") == fingerprint:
                return
            # 会话进行中的状态（ACTIVE/PAUSED）只在行动全部完成（{DONE}）时被指纹覆盖；
            # 否则保持现状——开始/暂停后 DS 行动状态尚未推进时，重新推断会把 ACTIVE 冲回 SCHEDULED
            if existing.get("state") in ("ACTIVE", "PAUSED") and action_states != {"DONE"}:
                existing["_fingerprint"] = fingerprint
                return
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
            "_fingerprint": fingerprint,
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

    # 4) 兜底：遍历所有 action 所在车辆的 vid，确保每个 vid 都有车型
    for stage in plan.get("stages", []) or []:
        team_actions = stage.get("team_actions", {})
        vehicles = []
        if isinstance(team_actions, dict):
            for vlist in team_actions.values():
                if isinstance(vlist, list):
                    vehicles.extend(vlist)
        elif isinstance(team_actions, list):
            for ta in team_actions:
                vehicles.extend(ta.get("car_actions", []) or [])
                vehicles.extend(ta.get("team_actions", []) or [])
        for v in vehicles:
            if isinstance(v, dict) and v.get("vid"):
                vid = v["vid"]
                if vid not in result or not result[vid]:
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
            "recon-and-strike": 22,
            # 旧命名别名（0912 MIGRATION 前）
            "search-and-shoot": 22,
            "recon-strike": 22,
            "rocket-strike": 23,
            "rocket-launch": 23,
            "loitering-munition-strike": 24,
            "loitering-munition-launch": 24,
            "machine-gun-strike": 25,
            "7.62mm-gun-shot": 25,
            "gun-shot": 25,
        }.get(t)

    # 侦打车 (sid 30~37，不含整车模式/自定义打击)
    if vt == "recon_strike":
        return {
            "lens-recon": 31,
            "recon-and-strike": 32,
            # 旧命名别名（0912 MIGRATION 前）
            "search-and-shoot": 32,
            "recon-strike": 32,
            "30mm-gun-strike": 33,
            "30mm-gun-launch": 33,
            "40mm-gun-launch": 33,
            "at-missile-strike": 34,
            "at-missile-launch": 34,
            "machine-gun-strike": 35,
            "7.62mm-gun-shot": 35,
            "gun-shot": 35,
        }.get(t)

    # 巡逻车 (sid 50~56，不含整车模式/自定义打击)
    if vt == "patrol":
        return {
            "lens-recon": 51,
            "recon-and-strike": 52,
            # 旧命名别名（0912 MIGRATION 前）
            "search-and-shoot": 52,
            "recon-strike": 52,
            "machine-gun-strike": 53,
            "7.62mm-gun-shot": 53,
            "gun-shot": 53,
            "sound-expel": 54,
            "acoustic-deterrence": 54,
            "light-expel": 55,
            "light-deterrence": 55,
        }.get(t)

    # 电磁车 (sid 40~48，不含整车模式)
    # 协议定义：42=DC突击，43=DC干扰
    if vt == "electronic":
        return {
            "em-recon": 41,
            "electronic-recon": 41,
            "recon-and-interfere": 42,
            # 旧命名别名（0912 MIGRATION 前）
            "em-assault": 42,
            "electronic-assault": 42,
            "em-interference": 43,
            "electronic-jamming": 43,
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
    if "30炮" in n or "30mm" in n or "40炮" in n or "40mm" in n:
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
    if "电磁突击" in n or "电磁压制" in n or "侦察干扰" in n:
        return 42
    if "电磁干扰" in n or "干扰" in n:
        return 43
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


def _to_str_coord(value, digits: int = 6) -> str:
    try:
        return f"{float(value or 0):.{digits}f}"
    except (TypeError, ValueError):
        return f"{0:.{digits}f}"


def _to_int_scaled(value, scale: float = 1.0) -> int:
    try:
        return int(float(value or 0) * scale)
    except (TypeError, ValueError):
        return 0


# ---------- 元任务经纬高坐标整型化缩放工具 ----------
# 数据服务器侧要求 lon/lat/alt 以整数存储，精度为 10^6（即 6 位小数）;
# 前端与本地 task_pool 仍保持十进制浮点数。
_COORD_FIELDS = {"lon", "lat", "alt", "longitude", "latitude", "altitude"}
_COORD_SCALE = 1_000_000


def _coord_to_int(value: Any, key: str = "") -> int:
    """将单个坐标值乘以 10^6 后取整；非法值返回 0。"""
    try:
        return int(float(value or 0) * _COORD_SCALE)
    except (TypeError, ValueError):
        return 0


def _coord_to_float(value: Any, key: str = "") -> Any:
    """将缩放后的整数坐标转回浮点。
    兼容旧数据：浮点数保持原样；字符串尝试解析为浮点；
    整数/整数形式浮点统一除以 10^6（按需求，数据服务器侧存储的坐标均为缩放后的整数）。
    对整数形式浮点做阈值判断，避免误除合法的未缩放小整数坐标。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value / _COORD_SCALE
    if isinstance(value, float):
        # 数据服务器某些实现可能把整型坐标序列化为 X.0 浮点
        if value.is_integer() and abs(value) >= 1000:
            return value / _COORD_SCALE
        return value
    if isinstance(value, str):
        try:
            s = value.strip()
            if s == "":
                return value
            v = float(s)
            if v.is_integer():
                return int(v) / _COORD_SCALE
            return v
        except (ValueError, TypeError):
            return value
    return value


def _transform_coords_in_param(param: Any, transform_fn) -> Any:
    """递归遍历 action.param 内的 dict/list，对坐标字段应用 transform_fn。"""
    if isinstance(param, list):
        return [_transform_coords_in_param(item, transform_fn) for item in param]
    if isinstance(param, dict):
        result = {}
        for k, v in param.items():
            if k in _COORD_FIELDS and v is not None:
                result[k] = transform_fn(v, k)
            else:
                result[k] = _transform_coords_in_param(v, transform_fn)
        return result
    return param


def _scale_coords_in_plan(plan: Dict[str, Any], transform_fn) -> Dict[str, Any]:
    """深拷贝 plan，并扫描所有 action.param 做坐标缩放/反缩放。"""
    plan = copy.deepcopy(plan)

    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            if "param" in obj and isinstance(obj["param"], dict):
                obj["param"] = _transform_coords_in_param(obj["param"], transform_fn)
            for v in obj.values():
                walk(v)

    walk(plan)
    return plan


def _scale_coords_to_int(plan: Dict[str, Any]) -> Dict[str, Any]:
    """把 plan 中所有 action.param 的经纬高坐标从浮点/字符串转为缩放后的整数。"""
    return _scale_coords_in_plan(plan, _coord_to_int)


def _scale_coords_to_float(plan: Dict[str, Any]) -> Dict[str, Any]:
    """把 plan 中所有 action.param 的经纬高坐标从缩放后的整数转回浮点（兼容旧字符串/浮点数据）。"""
    return _scale_coords_in_plan(plan, _coord_to_float)


# ---------- 坐标缩放工具结束 ----------


def _build_path_points(points):
    """自主机动/编队机动路径点：lon/lat/alt 以 10^6 缩放后的整数形式下发。"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        lon = pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0)
        lat = pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0)
        alt = pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0)
        result.append({
            "lon": _coord_to_int(lon),
            "lat": _coord_to_int(lat),
            "alt": _coord_to_int(alt),
            "radius": pt.get("radius", -1),
            "type": pt.get("type", 1),
        })
    return result


def _build_formation_points(points):
    """编队机动（sid=7）路径点：经纬高 + 相对头车的横/纵向偏移，不带 radius/type。"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        lon = pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0)
        lat = pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0)
        alt = pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0)
        result.append({
            "lon": _coord_to_int(lon),
            "lat": _coord_to_int(lat),
            "alt": _coord_to_int(alt),
            "offsetX": pt.get("offsetX", 0),
            "offsetY": pt.get("offsetY", 0),
        })
    return result


def _build_area_points(points):
    """侦察/电磁区域点：lon/lat/alt 以 10^6 缩放后的整数形式下发。"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        lon = pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0)
        lat = pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0)
        alt = pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0)
        result.append({
            "lon": _coord_to_int(lon),
            "lat": _coord_to_int(lat),
            "alt": _coord_to_int(alt),
        })
    return result


def _build_strike_points(points):
    """打击类目标点公共字段：lon/lat/alt 以 10^6 缩放后的整数形式下发。"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        lon = pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0)
        lat = pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0)
        alt = pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0)
        result.append({
            "lon": _coord_to_int(lon),
            "lat": _coord_to_int(lat),
            "alt": _coord_to_int(alt),
            "tart": pt.get("tart", 0),
            "attr": pt.get("attr", 0),
            "thr": pt.get("thr", 0),
            "dam": pt.get("dam", 0),
            "blk": pt.get("blk", 0),
            "figt": pt.get("figt", 0),
            "sug": pt.get("sug", 0),
        })
    return result


def _air_recon_alt_to_int(value: Any) -> int:
    """空中侦察航点高程：协议系数 10（协调卡-空地），非法值返回 0。"""
    try:
        return int(float(value or 0) * 10)
    except (TypeError, ValueError):
        return 0


def _build_air_recon_points(points):
    """空中侦察航路点：lon/lat 以 10^6、alt 以 10 缩放后的整数形式下发，保留飞行/相机扩展字段。"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        lon = pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0)
        lat = pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0)
        alt = pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0)
        result.append({
            "lon": _coord_to_int(lon),
            "lat": _coord_to_int(lat),
            "alt": _air_recon_alt_to_int(alt),
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
            "points": _build_formation_points(param.get("points")),
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
            "pose": param.get("pose", [0, 0, 0]),
            "pose_deviation": param.get("pose_deviation", [0, 0, 0]),
            "limited_speed": param.get("limited_speed", 10),
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

    # sid = 25/35/53: 机枪打击（简化字段：只保留 time/sort/num/points 中的 lon/lat/alt/tart）
    if sid in (25, 35, 53) and action_type in ("machine-gun-strike", "gun-shot", "7.62mm-gun-shot"):
        return {
            "sid": sid,
            "time": param.get("time", 60),
            "sort": param.get("sort", 0),
            "num": param.get("num", len(param.get("points", [])) or 1),
            "points": _build_gun_shot_points(param.get("points")),
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
            "lon": _coord_to_int(param.get("lon", 0)),
            "lat": _coord_to_int(param.get("lat", 0)),
            "alt": _coord_to_int(param.get("alt", 0)),
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

    # sid = 71: 空中侦察（service.points1/2/3 为三架无人机各自的航迹点数组，见 装备行动序列知识-0911 §6.2）
    if sid == 71:
        svc = param.get("service") if isinstance(param.get("service"), dict) else {}
        service = {
            "sid": 71,
            "type": param.get("type", 2),
            "mode": param.get("mode", 1),
            "time": param.get("time", 120),
        }
        for i in (1, 2, 3):
            service[f"points{i}"] = _build_air_recon_points(svc.get(f"points{i}"))
        return service

    # sid = 41: 电磁侦察
    if sid == 41:
        service = {
            "sid": 41,
            "type": param.get("type", 4),
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

    # sid = 42/43: 电磁突击 / 电磁干扰
    if sid in (42, 43):
        service = {
            "sid": sid,
            "type": param.get("type", 4),
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


def _build_gun_shot_points(points):
    """机枪打击目标点：lon/lat/alt 以 10^6 缩放后的整数形式下发，只保留 lon/lat/alt/tart。"""
    result = []
    for pt in points or []:
        if not isinstance(pt, dict):
            continue
        lon = pt.get("lon") if pt.get("lon") is not None else pt.get("longitude", 0)
        lat = pt.get("lat") if pt.get("lat") is not None else pt.get("latitude", 0)
        alt = pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0)
        result.append({
            "lon": _coord_to_int(lon),
            "lat": _coord_to_int(lat),
            "alt": _coord_to_int(alt),
            "tart": pt.get("tart", 0),
        })
    return result


# 兜底（已上移，保留此注释避免遗漏）
# return {"sid": 1, "points": [], "limited_speed": 20, "safe_mode": 0, "loop_mode": 0}


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
        # 优先用 plan.uuid（编辑保存时写入 DS 的六位整数），否则从 plan_id 提取数字/哈希
        uuid_tid = _tid_from_plan_uuid(plan)
        if uuid_tid is not None:
            tid = uuid_tid
        else:
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
                            at = a.get("action_type") or car_action_type
                            vehicle_actions_map[vid].append(dict(a, action_type=at))
        elif isinstance(team_actions, list):
            for ta in team_actions:
                team_id = ta.get("team_id", "")
                # 标准 /simple 接口使用 car_actions，旧接口使用 team_actions
                vehicles = ta.get("car_actions", ta.get("team_actions", []))
                for vehicle in vehicles:
                    vid = vehicle.get("vid", "")
                    actions = vehicle.get("actions", [])
                    car_action_type = vehicle.get("action_type", "")
                    if vid and actions:
                        if vid not in vehicle_actions_map:
                            vehicle_actions_map[vid] = []
                        for a in actions:
                            at = a.get("action_type") or car_action_type
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
            # 优先从车辆控制服务缓存取 VMF
            vmf = vehicle_control_client.get_vehicle_vmf(vid)
        if vmf is None:
            # 其次从资源池在线车辆取 VMF
            rp_info = get_online_vehicle_info_from_resource_pool(vid)
            vmf = rp_info.get("vmf") if rp_info else None
        if vmf is None:
            # 尝试 vid 本身就是数字
            try:
                vmf = int(vid)
            except (ValueError, TypeError):
                vmf = 99076716  # 兜底：ZD01 的示例 vmf

        vip = (vehicle_ips or {}).get(vid)
        if vip is None:
            # 优先从车辆控制服务缓存取 IP
            vip = vehicle_control_client.get_vehicle_ip(vid)
        if vip is None:
            # 其次从资源池在线车辆取 IP
            rp_info = get_online_vehicle_info_from_resource_pool(vid)
            vip = rp_info.get("ip") if rp_info else None
        if vip is None:
            vip = "192.168.1.11"  # 兜底 IP
        num = len(actions)

        acts = []
        vehicle_type = vid_vehicle_type_map.get(vid, "")
        for idx, action in enumerate(actions, start=1):
            service = _build_service_from_action(action, vehicle_type)
            param = action.get("param") or {}
            strategy = _parse_mission_strategy(param)
            act_start, act_end = _parse_mission_start_end(param, start_str, end_str)
            act: Dict[str, Any] = {
                "aid": idx,
                "num": num,
                "vid": [vmf],
                "vip": [vip],
                "strategy": strategy,
                "premise": list(range(1, idx)),  # 前置为前面所有 action
                "endwith": -1,
                "level": 0,
                "service": service,
            }
            # 只有真正设置了开始时间/时长时才下发 start/end，避免传默认值
            if act_start and act_end:
                act["start"] = act_start
                act["end"] = act_end
            acts.append(act)

        mission_vehicles.append({
            "vid": vmf,
            "cnt": f"{vid}任务",
            "num": num,
            "acts": acts,
        })

    # 任务整体时间：取所有 action 最早 start 和最晚 end；没有则用默认值
    task_start, task_end = start_str, end_str
    all_starts = []
    all_ends = []
    for acts in (v.get("acts") or [] for v in mission_vehicles):
        for act in acts:
            if act.get("start"):
                all_starts.append(act["start"])
            if act.get("end"):
                all_ends.append(act["end"])
    if all_starts:
        task_start = min(all_starts)
    if all_ends:
        task_end = max(all_ends)

    mission_data = {
        "task": {
            "tid": tid,
            "type": 0,
            "cnt": title or f"任务{plan_id}",
            "start": task_start,
            "end": task_end,
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


def _tid_from_plan_uuid(plan: Optional[Dict[str, Any]]) -> Optional[int]:
    """取 plan.uuid 作为 tid（编辑保存时写入 DS 的六位整数）；没有或非法时返回 None"""
    uuid_val = (plan or {}).get("uuid")
    if uuid_val is None or uuid_val == "":
        return None
    try:
        return int(uuid_val)
    except (TypeError, ValueError):
        return None


def _resolve_plan_tid(plan_id: str) -> int:
    """control_mission 的 taskid：优先 plan.uuid（与 send_mission 下发的 tid 保持一致，
    否则车辆侧按 taskid 匹配不到任务），兜底从 plan_id 推导。
    操控席 plan 在数据服务器，协同席 plan 在协同席数据服务器，两边都试。"""
    for getter in (get_plan_detail_operator, get_plan_detail):
        try:
            uuid_tid = _tid_from_plan_uuid(getter(plan_id))
        except Exception:
            uuid_tid = None
        if uuid_tid is not None:
            return uuid_tid
    return _plan_id_to_tid(plan_id)


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
    # taskid 优先取 plan.uuid（编辑保存时写入 DS），与 send_mission 下发的 tid 保持一致
    tid = _resolve_plan_tid(plan_id)

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


# ==================== MissionService set_cooperative_authorization 相关 ====================


def build_cooperative_authorization_payload(
    source: int = 1,
    command: int = 1,
    vehicles: Optional[List[Dict[str, Any]]] = None,
    target_type: Optional[int] = None,
    priorities: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """构建 MissionService set_cooperative_authorization 的 payload（0x02A20808）。

    注意：command=2（解除授权）也必须携带 vehicles / target_type / priorities 完整字段——
    二进制协议（0x02A20808）报文字段齐全，MissionService 对缺字段的 JSON 会直接丢弃
    不回 ack（2026-09-09 实测：command=2 只带 source/command 时 zenoh 侧无响应）。
    解除授权时应回传下发授权时的同一组参数。
    """
    args: Dict[str, Any] = {
        "source": source,
        "command": command,
        "vehicles": list(vehicles or []),
        "target_type": target_type if target_type is not None else 0,
        "priorities": list(priorities or []),
    }
    return {
        "service": "MissionService",
        "action": "set_cooperative_authorization",
        "args": args,
    }


def publish_cooperative_authorization(
    vehicle_vid: str,
    source: int = 1,
    command: int = 1,
    vehicles: Optional[List[Dict[str, Any]]] = None,
    target_type: Optional[int] = None,
    priorities: Optional[List[int]] = None,
) -> tuple[bool, str]:
    """通过 Zenoh 向本车发送 set_cooperative_authorization。

    Args:
        vehicle_vid: 本车 vid（topic 中的车辆；会去掉 equipment: 前缀）
        command: 1=下发授权，2=解除授权

    Returns:
        (success, message)
    """
    import json

    vid = vehicle_vid.replace("equipment:", "") if vehicle_vid else vehicle_vid
    topic = f"op/t01/g01/v{vid}/cmd/MissionService/set_cooperative_authorization"
    payload = build_cooperative_authorization_payload(source, command, vehicles, target_type, priorities)
    print(f"[ZENOH-COOP] topic={topic} | payload={json.dumps(payload, ensure_ascii=False)}")

    ok = zenoh_client.publish(topic, payload)
    if ok:
        action_text = "下发授权" if command == 1 else "解除授权"
        return True, f"set_cooperative_authorization({action_text}) 已下发 | topic={topic}"
    err = zenoh_client.get_last_zenoh_error()
    print(f"[ZENOH-COOP] publish failed: {err}")
    return False, f"Zenoh 下发失败: {err}"


# ==================== 编队机动任务下发（POST /formation/mission/send）相关 ====================


def _is_formation_move_action(action: Dict[str, Any]) -> bool:
    """判断 action 是否为编队机动元任务。

    兼容 DS 投影把 action_type 写成 Unknown_Action 的情况：依次按
    action_type / param 结构 / 名称 推断。
    """
    at = (action.get("action_type") or "").strip().lower()
    if at == "formation-move":
        return True
    if _infer_action_type_from_param(action.get("param")) == "formation-move":
        return True
    name = action.get("action_name") or action.get("name") or ""
    return _infer_action_type_from_name(name) == "formation-move"


def _extract_formation_sub_plan(plan: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """从 plan 中抽取仅含编队机动行动的子 plan（供编队任务下发构建 body）。

    - 只保留含编队机动行动的车辆（car_actions），且每车只保留编队机动行动
    - 头车（param.is_leader 为真）排在 car_actions 第一位：DS 投影会按资源 id
      重排 car_actions，顺序信息只能靠业务字段（is_leader）恢复
    - vehicle_summary 直接剔除，避免 build_mission_data 把非编队行动重复拉入

    Returns:
        (子 plan, 头车 vid 或 None)
    """
    sub = copy.deepcopy(plan)
    sub.pop("vehicle_summary", None)
    leader_vid: Optional[str] = None
    for stage in sub.get("stages", []) or []:
        team_actions = stage.get("team_actions")
        if isinstance(team_actions, dict):
            team_actions = [
                {"team_id": team_id, "car_actions": vehicles}
                for team_id, vehicles in team_actions.items()
            ]
            stage["team_actions"] = team_actions
        if not isinstance(team_actions, list):
            continue
        for ta in team_actions:
            key = "car_actions" if "car_actions" in ta else "team_actions"
            kept = []
            for ca in ta.get(key) or []:
                actions = [a for a in (ca.get("actions") or []) if _is_formation_move_action(a)]
                if not actions:
                    continue
                ca["actions"] = actions
                if leader_vid is None and any((a.get("param") or {}).get("is_leader") for a in actions):
                    leader_vid = ca.get("vid")
                kept.append(ca)
            ta[key] = kept
    # 第二遍统一排序：保证头车在所有 car_actions 中排第一（含跨 team 的兜底场景）
    if leader_vid:
        for stage in sub.get("stages", []) or []:
            for ta in stage.get("team_actions", []) or []:
                for key in ("car_actions", "team_actions"):
                    if isinstance(ta.get(key), list):
                        ta[key].sort(key=lambda ca: 0 if ca.get("vid") == leader_vid else 1)
    return sub, leader_vid


def build_formation_mission_body(plan: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str], Optional[str]]:
    """构建编队机动任务下发的 HTTP 请求体。

    body 为 {"task": ...}（与 mission_data 结构一致），
    vehicles 数组头车排第一，且只包含编队机动行动。

    Returns:
        (body, 编队车辆 vid 列表（与 vehicles 同序，头车在前）, 头车 vid 或 None)
    """
    sub, leader_vid = _extract_formation_sub_plan(plan)
    mission_data = build_mission_data(sub)
    vids_in_order: List[str] = []
    for stage in sub.get("stages", []) or []:
        for ta in stage.get("team_actions", []) or []:
            for ca in (ta.get("car_actions") or ta.get("team_actions") or []):
                if ca.get("actions"):
                    vids_in_order.append(ca.get("vid", ""))
    return mission_data, vids_in_order, leader_vid


def publish_formation_mission_if_any(plan_id: str) -> Dict[str, Any]:
    """协同席下发的附加逻辑：plan 含编队机动元任务时，POST 到编队任务下发接口。

    POST FORMATION_MISSION_SEND_URL（车辆管理/编队服务 25.11.1.3:28410
    /formation/mission/send），body 为 {"task": ...}，vehicles 数组头车排第一。
    该附加发送失败不影响原下发结果。
    """
    plan = get_plan_detail(plan_id)
    if not plan:
        return {"sent": False, "reason": "plan not found"}
    body, vids, leader_vid = build_formation_mission_body(plan)
    if not vids:
        return {"sent": False, "reason": "no formation-move action"}
    tid = body["task"]["tid"]
    result: Dict[str, Any] = {
        "sent": True,
        "ok": False,
        "url": FORMATION_MISSION_SEND_URL,
        "leader_vid": leader_vid,
        "tid": tid,
        "vehicle_count": len(vids),
    }
    if not HAS_REQUESTS:
        result["sent"] = False
        result["error"] = "requests not available"
        return result
    try:
        resp = requests.post(
            FORMATION_MISSION_SEND_URL,
            json=body,
            timeout=10,
            proxies={"http": None, "https": None},
        )
        result["ok"] = resp.ok
        result["status_code"] = resp.status_code
        print(f"[FORMATION-HTTP] POST {FORMATION_MISSION_SEND_URL} | status={resp.status_code} | tid={tid} | leader={leader_vid} | vehicles={vids}")
        try:
            result["response"] = resp.json()
        except Exception:
            result["response_text"] = resp.text[:500]
    except Exception as e:
        result["error"] = str(e)
        print(f"[FORMATION-HTTP] POST {FORMATION_MISSION_SEND_URL} failed | tid={tid} | error={e}")
    return result


# ========== 车辆类型与资源池映射 ==========

VEHICLE_TYPE_DISPLAY_NAMES = {
    "Fire-Support-UGV": "火力车",
    "Recon-Strike-UGV": "侦打车",
    "Patrol-UGV": "巡逻车",
    "Electronic-UGV": "电磁车",
    "Air-Ground-UAV": "空地车",
    # 远程操控车（CK车）：规范值 Remote-Control-Car，历史数据兼容 Control-UGV
    "Remote-Control-Car": "操控车",
    "Control-UGV": "操控车",
}

# 各车型默认支持的载荷 action_type（用于前端新建行动序列时初始化节点）。
# 底盘类元任务（Auto-Move/Follow-Move/Silent-Guard 等）对所有车型通用，不在这里维护。
VEHICLE_ACTION_TYPES = {
    "Fire-Support-UGV": [
        "Lens-Recon", "Recon-And-Strike", "Machine-Gun-Strike",
        "Rocket-Strike", "Loitering-Munition-Strike",
    ],
    "Recon-Strike-UGV": [
        "Lens-Recon", "Recon-And-Strike", "30mm-Gun-Strike",
        "AT-Missile-Strike", "Machine-Gun-Strike",
    ],
    "Patrol-UGV": [
        "Lens-Recon", "Recon-And-Strike", "Machine-Gun-Strike",
        "Sound-Expel", "Light-Expel",
    ],
    "Electronic-UGV": ["EM-Recon", "Recon-And-Interfere", "EM-Interference", "Payload-Silent"],
    "Air-Ground-UAV": ["Air-Recon"],
    # 远程操控车：仅自主机动 + 编队机动（装备行动序列知识 第 7 节）
    "Remote-Control-Car": ["Auto-Move", "Formation-Move"],
}

# 资源池返回的 resource_type / model_type.description -> 内部车型映射
_RESOURCE_TYPE_TO_VEHICLE = {
    # 常见 resource_type / model_type 写法
    "Fire-Support-UGV": "Fire-Support-UGV",
    "Recon-Strike-UGV": "Recon-Strike-UGV",
    "Patrol-UGV": "Patrol-UGV",
    "Electronic-UGV": "Electronic-UGV",
    "EM-UGV": "Electronic-UGV",
    "Air-Ground-UAV": "Air-Ground-UAV",
    "KD-UGV": "Air-Ground-UAV",
    # 远程操控车（CK车）
    "Remote-Control-Car": "Remote-Control-Car",
    "Control-UGV": "Remote-Control-Car",
    # 中文描述兜底
    "无人火力车": "Fire-Support-UGV",
    "无人侦察车": "Recon-Strike-UGV",
    "无人巡逻车": "Patrol-UGV",
    "无人电磁车": "Electronic-UGV",
    "无人空地车": "Air-Ground-UAV",
    "空地车": "Air-Ground-UAV",
}


def _infer_vehicle_type(equipment: Dict[str, Any]) -> str:
    """从资源池 equipment 记录推断内部车辆类型。

    真实装备编号前缀优先级最高，用于覆盖资源池中可能错误的 resource_type。
    """
    rid = (equipment.get("resource_id") or "").strip()
    # 1) 优先按真实装备编号前缀推断
    inferred_from_vid = _infer_resource_type_from_vid(rid)
    if inferred_from_vid:
        return inferred_from_vid

    # 2) 其次使用 resource_type
    rt = (equipment.get("resource_type") or "").strip()
    if rt in VEHICLE_TYPE_DISPLAY_NAMES:
        return rt
    if rt in _RESOURCE_TYPE_TO_VEHICLE:
        return _RESOURCE_TYPE_TO_VEHICLE[rt]

    # 3) 再次 model_type.description / model_type.type
    model = equipment.get("model_type") or {}
    for key in ("description", "type"):
        md = (model.get(key) or "").strip()
        if md in VEHICLE_TYPE_DISPLAY_NAMES:
            return md
        if md in _RESOURCE_TYPE_TO_VEHICLE:
            return _RESOURCE_TYPE_TO_VEHICLE[md]

    # 4) 兜底：返回原始 resource_type，让前端自行决定展示/映射
    return rt or "Unknown"


# 在线车辆类型缓存：vid -> resource_type
# 在 _fetch_vehicles_from_resource_pool 调用时更新，用于 _to_frontend_plan
# 中 teams 只有 vid 字符串时也能正确识别车型。
_online_vehicle_type_cache: Dict[str, str] = {}

# 单查资源池得到的 vid（去 equipment: 前缀）-> resource_type 缓存；仅缓存成功结果，失败下次重试
_single_vehicle_type_cache: Dict[str, str] = {}


def _lookup_vehicle_type_from_resource_pool(vid: str) -> str:
    """按 vid 单查资源池 equipment 记录推断车型。

    用于 plan 数据无 resource_type 且 vid 无前缀特征（如操控车 vid=00）的场景；
    资源池单条查询不受 CK 车默认过滤影响（见 resource_pool_CK车查询接口说明）。
    """
    clean = (vid or "").replace("equipment:", "")
    if not clean:
        return ""
    if clean in _single_vehicle_type_cache:
        return _single_vehicle_type_cache[clean]
    rt = ""
    data = _http_get_resource_pool(f"/api/v1/resource_pool/resources/equipment:{clean}", silent=True)
    if isinstance(data, dict):
        inferred = _infer_vehicle_type(data)
        rt = "" if inferred in ("", "Unknown") else inferred
    if rt:
        _single_vehicle_type_cache[clean] = rt
    return rt


def _transform_equipment_to_vehicle(equipment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把资源池 equipment 记录转换为前端需要的 vehicle 结构。"""
    rid = equipment.get("resource_id", "")
    if not rid:
        return None

    vehicle_type = _infer_vehicle_type(equipment)
    if not vehicle_type or vehicle_type == "Unknown":
        # 无法识别的类型，跳过（或保留原始类型由前端处理）
        return None

    # 尝试从 resource_detail 取 VMF；取不到时保留 None
    resource_detail = (equipment.get("attributes") or {}).get("resource_detail") or {}
    vmf_raw = resource_detail.get("VMF") or resource_detail.get("vmf")
    vmf = None
    if vmf_raw is not None:
        try:
            vmf = int(vmf_raw)
        except (ValueError, TypeError):
            vmf = None

    return {
        "vid": rid,
        "resource_name": equipment.get("resource_name") or rid.replace("equipment:", ""),
        "resource_type": vehicle_type,
        "display_name": VEHICLE_TYPE_DISPLAY_NAMES.get(vehicle_type, vehicle_type),
        "supported_action_types": VEHICLE_ACTION_TYPES.get(vehicle_type, []),
        "online_status": equipment.get("online_status") or "UNKNOWN",
        "vmf": vmf,
        "ip": resource_detail.get("ip") or equipment.get("ip") or "25.11.1.1",
        "is_mock": False,
    }


def _fetch_vehicles_from_resource_pool() -> List[Dict[str, Any]]:
    """内部：从资源池获取车辆列表。优先 online，若没有则回退全部 equipment。"""
    # 1) 优先获取 online 车辆
    data = _http_get_resource_pool(
        "/api/v1/resource_pool/resources",
        params={"is_online": "true", "entity_kind": "equipment", "limit": 100},
        silent=False,
    )
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("items") or data.get("data") or []

    # 2) 没有 online 车辆时，尝试获取全部 equipment（可能资源池未标记在线状态）
    if not items:
        data = _http_get_resource_pool(
            "/api/v1/resource_pool/resources",
            params={"entity_kind": "equipment", "limit": 100},
            silent=False,
        )
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("items") or data.get("data") or []

    result = []
    for item in items:
        vehicle = _transform_equipment_to_vehicle(item)
        if vehicle:
            result.append(vehicle)
            _online_vehicle_type_cache[vehicle["vid"]] = vehicle["resource_type"]
    return result


def query_online_vehicles() -> List[Dict[str, Any]]:
    """从资源池查询当前已连接（online）的无人车列表。

    资源池服务独立部署在 28800 端口（与 task_pool 28801 区分）。
    资源池不可达或没有可识别车辆时返回空列表。
    """
    result = _fetch_vehicles_from_resource_pool()
    if result:
        return result
    print("[AS-DEBUG] query_online_vehicles: no vehicles from resource_pool")
    return []


def query_online_vehicles_operator() -> List[Dict[str, Any]]:
    """从资源池查询当前已连接（online）的无人车列表（操控席视角，资源池服务共用）。"""
    result = _fetch_vehicles_from_resource_pool()
    if result:
        return result
    print("[AS-DEBUG] query_online_vehicles_operator: no vehicles from resource_pool")
    return []


def get_online_vehicle_info_from_resource_pool(vid: str) -> Optional[Dict[str, Any]]:
    """从资源池在线车辆列表中查找指定 vid 的信息（用于车辆控制服务缺失时的兜底）。"""
    clean_vid = vid.replace("equipment:", "") if vid else vid
    for v in query_online_vehicles_operator():
        if v.get("vid", "").replace("equipment:", "") == clean_vid:
            return v
    return None


# ==================== 操控席数据服务端接口 ====================


def query_plans_operator(limit: int = 200) -> List[Dict[str, Any]]:
    """向操控席数据服务器查询行动方案列表 — POST /resources/query（静默模式）。
    任务列表直接从数据服务器拉取，不使用本地缓存/假数据。"""
    data = _http_post_operator(
        "/api/v1/task_pool/resources/query",
        {"task_type": "PLAN", "limit": limit},
        silent=False,
        timeout=(1, 30),
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

    items.sort(key=_plan_sort_key)

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
            "vehicle_summary": _build_vehicle_summary_brief(item),
        })
    return result


def _fetch_plan_uuid_from_raw(rid: str) -> Optional[Any]:
    """从 DS 全文档的 raw_payload 取 plan.uuid。

    当前 DS 版本的 PLAN 类型投影未注册 uuid 字段，/simple 与类型化查询均不返回；
    import 时 uuid 仅保留在 raw_payload 中，需补一次全文档查询取回（读 plan 以顶层
    投影为准的例外：uuid 在投影中不存在，raw_payload 是唯一载体）。若 DS 后续把
    uuid 注册进 PLAN schema，顶层投影会先命中，本函数不再被调用。
    """
    full = _http_get_operator(f"/api/v1/task_pool/resources/{rid}", silent=True)
    if not isinstance(full, dict):
        return None
    raw = full.get("raw_payload")
    if isinstance(raw, dict):
        return raw.get("uuid")
    return None


def get_plan_detail_operator(plan_id: str) -> Optional[Dict[str, Any]]:
    """向操控席数据服务器获取方案详情（静默模式）。
    任务详情直接从数据服务器拉取，不使用本地缓存。"""
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    data = _http_get_operator(f"/api/v1/task_pool/resources/simple/{rid}", silent=False)
    if data is None or not isinstance(data, dict):
        print(f"[AS-DEBUG] get_plan_detail_operator: plan not found or data server unreachable, plan_id={plan_id}")
        return None

    plan = _normalize_plan_field_names(data)
    plan = _scale_coords_to_float(plan)
    if plan.get("uuid") is None:
        uuid_val = _fetch_plan_uuid_from_raw(rid)
        if uuid_val is not None:
            plan["uuid"] = uuid_val

    car_actions = _build_car_actions_from_plan(plan, http_post=_http_post_operator)
    result = _to_frontend_plan(plan, car_actions)
    # 根据数据服务端中的 action 状态推断并初始化运行时状态（避免前后端不一致）
    action_runtime.init_state_from_plan(plan_id, result)
    return result


def import_plan_to_operator(plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将行动方案 import 到操控席数据服务器；写入前将经纬高坐标缩放为整数。

    plan 来自前端（本地命名），写入前需把 teams 的 name/vehicles 转为
    DS 原生命名 team_name/team_equipments，否则 DS 生成默认编组名且丢车辆。
    """
    result = _http_post_operator(
        "/api/v1/task_pool/ingestion/import",
        {"resources": [_scale_coords_to_int(_to_ds_native_field_names(plan))], "return_data_type": "typed", "ignore_errors": True},
    )
    return result


_PLAN_SEQ_ID_RE = re.compile(r"^plan-(\d+)$", re.IGNORECASE)


def _next_sequential_plan_id(plan_ids) -> str:
    """取现有 plan-<数字> 形式 id 的数字后缀最大值 +1，格式 plan-六位数字（超出 6 位继续递增）"""
    max_num = 0
    for pid in plan_ids:
        m = _PLAN_SEQ_ID_RE.match(str(pid or ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"plan-{max_num + 1:06d}"


def _generate_operator_plan_id() -> str:
    """新建操控席方案的兜底 plan id：顺序号 plan-六位数字。

    编号依据本地 task_pool 与操控席数据服务器（不可达时仅用本地）中已有的 PLAN 资源。
    """
    ids = [p.get("plan_id") or p.get("resource_id", "") for p in task_pool.query(task_type="PLAN")]
    try:
        ids += [p.get("plan_id") or p.get("resource_id", "") for p in query_plans_operator()]
    except Exception:
        pass
    return _next_sequential_plan_id(ids)


def create_operator_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """在本地 task_pool 创建/保存一个新的 PLAN 资源；操控席数据服务器不可达时作为兜底"""
    from app.services.task_pool import task_pool

    plan_id = plan.get("plan_id") or plan.get("resource_id", "").replace("plan:", "")
    if not plan_id:
        plan_id = _generate_operator_plan_id()
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

    # 确保每个 action 的 start_time / mission_duration 有有效默认值
    _normalize_action_timing(plan)

    # 尝试导入数据服务器；失败或不可达则仅保存本地
    try:
        import_plan_to_operator(plan)
    except Exception:
        pass

    task_pool.set(rid, {**plan, "_seat": "operator"})
    return task_pool.get(rid)


def create_coordination_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """协同席 — 新建空方案（通常仅标题，无行动序列数据），import 写入协同席数据服务器。

    plan_id 未传时按 plan-六位数字 顺序号兜底生成（依据协同席数据服务器与本地缓存，
    与操控席 _generate_operator_plan_id 同策略）。数据服务器不可达时仅保存本地缓存，
    标记 local_dirty 待后续 sync 补偿。
    """
    from app.services.task_pool import task_pool

    plan_id = plan.get("plan_id") or plan.get("resource_id", "").replace("plan:", "")
    if not plan_id:
        ids = [p.get("plan_id") or p.get("resource_id", "") for p in task_pool.query(task_type="PLAN")]
        try:
            ids += [p.get("plan_id") or p.get("resource_id", "") for p in query_plans()]
        except Exception:
            pass
        plan_id = _next_sequential_plan_id(ids)
        plan["plan_id"] = plan_id

    rid = plan.get("resource_id") or f"plan:{plan_id}"
    plan["resource_id"] = rid
    plan["task_type"] = "PLAN"

    try:
        ok = _import_plan_payload(rid, plan, _http_post, label="data_server")
    except Exception:
        ok = False

    task_pool.set(rid, {**plan, "_seat": "data_server", "local_dirty": not ok})
    return task_pool.get(rid)


def update_plan_locally(plan_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
    # 确保每个 action 的 start_time / mission_duration 有有效默认值
    _normalize_action_timing(existing)
    # 标记本地 plan 已被修改但尚未成功同步到数据服务器
    existing["local_dirty"] = True
    task_pool.set(rid, existing)
    return task_pool.get(rid)


# 兼容旧名：操控席本地更新与协同席共用同一套本地更新逻辑
update_operator_plan_locally = update_plan_locally


# 前端编辑保存传入的字段名 → DS 文档字段名（写回保持 DS 原始命名）
_UPDATE_PLAN_KEY_MAP = {"title": "plan_title", "description": "plan_description"}


def update_plan(plan_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """协同席 — 直读数据服务器全文档，应用白名单字段修改后 import 写回。

    写回以 DS 原始命名为准（payload 中的前端命名 title/description 映射为
    plan_title/plan_description）；返回给调用方（前端）的是归一化命名的副本。
    数据服务器不可达时退回同席位本地缓存编辑，标记 local_dirty 待后续 sync 补偿。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"
    allowed_top_keys = {"title", "description", "state", "teams", "targets", "stages", "search_text", "car_actions", "vehicle_summary"}

    plan = _fetch_plan_document(rid, _http_get, label="data_server")
    if plan is None:
        plan = _get_cached_plan_for_seat(rid, "data_server")
    if plan is None:
        return None

    for key, value in payload.items():
        if key in allowed_top_keys:
            plan[_UPDATE_PLAN_KEY_MAP.get(key, key)] = copy.deepcopy(value)
    # 确保每个 action 的 start_time / mission_duration 有有效默认值
    _normalize_action_timing(plan)

    ok = _import_plan_payload(rid, plan, _http_post, label="data_server")
    plan["local_dirty"] = not ok
    _cache_plan(rid, plan, "data_server")
    # 返回给前端的副本归一化命名（title/name/vehicles），不影响写回与缓存的 DS 原文
    return _normalize_plan_field_names(copy.deepcopy(plan))


def _is_empty_or_zero_list(value):
    """判断列表是否为空或所有元素均为 0/空值（用于识别被投影丢失的列表参数）"""
    if not isinstance(value, list) or len(value) == 0:
        return True

    def _is_zero(v):
        if v in (0, 0.0, None, "", "0", "0.0", "0.00"):
            return True
        if isinstance(v, str):
            try:
                return float(v.strip()) == 0
            except (TypeError, ValueError):
                return False
        return False

    for item in value:
        if not isinstance(item, dict):
            return False
        for v in item.values():
            if not _is_zero(v):
                return False
    return True


def _merge_action_param(local_param, remote_param):
    """合并本地与远程 action.param：当远程列表参数为空/全 0 而本地有有效数据时，保留本地数据。"""
    if not isinstance(local_param, dict):
        return remote_param
    if not isinstance(remote_param, dict):
        return copy.deepcopy(local_param)
    merged = copy.deepcopy(remote_param)
    list_fields = ("area", "points", "frequency", "waypoints")
    for field in list_fields:
        local_val = local_param.get(field)
        remote_val = remote_param.get(field)
        if (
            _is_empty_or_zero_list(remote_val)
            and isinstance(local_val, list)
            and len(local_val) > 0
            and not _is_empty_or_zero_list(local_val)
        ):
            merged[field] = copy.deepcopy(local_val)
    for field in ("direct", "protect"):
        local_val = local_param.get(field)
        remote_val = remote_param.get(field)
        if (not remote_val or not isinstance(remote_val, dict)) and isinstance(local_val, dict) and local_val:
            merged[field] = copy.deepcopy(local_val)
    return merged


def _flatten_plan_actions(plan):
    """把 plan.stages.team_actions 中的 action 展平，便于按 action_id/vid/seq 匹配。"""
    results = []
    for stage in plan.get("stages", []) or []:
        stage_id = stage.get("stage_id", "")
        team_actions = stage.get("team_actions", {})
        vehicles = []
        if isinstance(team_actions, dict):
            for vlist in team_actions.values():
                if isinstance(vlist, list):
                    vehicles.extend(vlist)
        elif isinstance(team_actions, list):
            for ta in team_actions:
                vehicles.extend(ta.get("car_actions", []) or [])
                vehicles.extend(ta.get("team_actions", []) or [])
        for vehicle in vehicles:
            if not isinstance(vehicle, dict):
                continue
            vid = vehicle.get("vid", "")
            for action in vehicle.get("actions", []) or []:
                if not isinstance(action, dict):
                    continue
                results.append({
                    "stage_id": stage_id,
                    "vid": vid,
                    "action_id": action.get("action_id", ""),
                    "action_seq": action.get("action_seq", 0),
                    "param": action.get("param", {}),
                })
    return results


def _merge_plan_keep_local_params(local_plan, remote_plan):
    """用远程 plan 更新本地缓存，但保留本地有效的 action.param 列表数据，防止 /simple 投影丢失。"""
    if not isinstance(remote_plan, dict):
        return copy.deepcopy(local_plan) if isinstance(local_plan, dict) else {}
    if not isinstance(local_plan, dict):
        # 本地无缓存时直接返回远程 plan
        return copy.deepcopy(remote_plan)
    merged = copy.deepcopy(remote_plan)
    local_actions = _flatten_plan_actions(local_plan)
    # 建立索引：优先 action_id，其次 (vid, stage_id, action_seq)
    by_id = {}
    by_key = {}
    for a in local_actions:
        aid = a.get("action_id")
        if aid:
            by_id[aid] = a
        key = (a.get("vid"), a.get("stage_id"), a.get("action_seq"))
        by_key[key] = a

    for stage in merged.get("stages", []) or []:
        team_actions = stage.get("team_actions", {})
        vehicles = []
        if isinstance(team_actions, dict):
            for vlist in team_actions.values():
                if isinstance(vlist, list):
                    vehicles.extend(vlist)
        elif isinstance(team_actions, list):
            for ta in team_actions:
                vehicles.extend(ta.get("car_actions", []) or [])
                vehicles.extend(ta.get("team_actions", []) or [])
        for vehicle in vehicles:
            if not isinstance(vehicle, dict):
                continue
            vid = vehicle.get("vid", "")
            for action in vehicle.get("actions", []) or []:
                if not isinstance(action, dict):
                    continue
                local_action = by_id.get(action.get("action_id"))
                if not local_action:
                    local_action = by_key.get((vid, stage.get("stage_id", ""), action.get("action_seq", 0)))
                if local_action:
                    action["param"] = _merge_action_param(local_action.get("param", {}), action.get("param", {}))
    return merged


def sync_plan_to_data_server(
    plan_id: str,
    http_post,
    http_get,
    label: str = "data_server",
) -> bool:
    """把 plan 通过 ingestion/import 同步到指定数据服务器。

    数据源优先级：
      1. 本地缓存中有未推送的修改（local_dirty 且属于本席位）→ 推送本地；
      2. 数据服务器全文档（/resources/{rid}，非 /simple 投影）→ 以 DS 为准刷新；
      3. 数据服务器不可达时，回退同席位本地缓存。
    经过测试，PATCH /resources/{rid} 无法保存 stages.team_actions 等嵌套字段，
    因此改用全量 import 方式 upsert，确保行动序列数据落盘到数据服务器。
    """
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"

    local = _get_cached_plan_for_seat(rid, label)
    if local and local.get("local_dirty"):
        plan = local
    else:
        plan = _fetch_plan_document(rid, http_get, label=label)
        if plan is None:
            plan = local  # 数据服务器不可达，本地兜底
    if not plan:
        return False

    # 同步前确保时间参数有效，避免数据服务器保存空/0 值
    _normalize_action_timing(plan)
    try:
        ok = _import_plan_payload(rid, plan, http_post, label=label)
        if ok:
            plan["local_dirty"] = False
        else:
            plan["local_dirty"] = True
        _cache_plan(rid, plan, label)
        if ok:
            print(f"[SYNC-PLAN] synced plan to {label}, plan_id={plan_id}")
        return ok
    except Exception as e:
        print(f"[SYNC-PLAN] sync to {label} failed: {e}")
        return False


def sync_plan_to_operator(plan_id: str) -> bool:
    """把本地 task_pool 中的 plan 同步到操控席数据服务器。"""
    return sync_plan_to_data_server(plan_id, _http_post_operator, _http_get_operator, label="operator")


def _cascade_delete_resource(
    resource_id: str,
    http_post,
    label: str = "data_server",
) -> Optional[Dict[str, Any]]:
    """调用数据服务器级联删除接口，将目标资源及其子资源标记为 DELETED。

    接口：POST /api/v1/task_pool/resources/{resource_id}/delete，body {"cascade": true}
    返回 None 表示调用失败。
    """
    if not resource_id:
        return None
    try:
        resp = http_post(
            f"/api/v1/task_pool/resources/{resource_id}/delete",
            {"cascade": True},
            silent=False,
        )
        if resp is not None and isinstance(resp, dict):
            return resp
        print(f"[DELETE-VEHICLE] cascade delete {resource_id} from {label} returned non-dict: {resp}")
        return None
    except Exception as e:
        print(f"[DELETE-VEHICLE] cascade delete {resource_id} from {label} failed: {e}")
        return None


def _cascade_delete_resource_on_operator(resource_id: str) -> Optional[Dict[str, Any]]:
    """调用操控席数据服务器级联删除接口。"""
    return _cascade_delete_resource(resource_id, _http_post_operator, label="operator")


def _normalize_car_action_resource_id(ca: Dict[str, Any]) -> Optional[str]:
    """从 car_action 对象中提取并规范化资源 ID。"""
    ca_rid = ca.get("resource_id") or ca.get("car_actions_id") or ca.get("car_action_id")
    if not ca_rid:
        return None
    if not ca_rid.startswith(("car_actions:", "car_action:")):
        ca_rid = f"car_actions:{ca_rid}"
    return ca_rid


def _delete_vehicle_from_plan(
    plan_id: str,
    vid: str,
    http_post,
    http_get,
    label: str = "data_server",
) -> Dict[str, Any]:
    """删除指定方案中某车辆的行动序列，并同步到指定数据服务器。"""
    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"
    # 直读数据服务器全文档；不可达时回退同席位本地缓存
    plan = _fetch_plan_document(rid, http_get, label=label)
    if not plan:
        plan = _get_cached_plan_for_seat(rid, label)
    if not plan:
        return {"ok": False, "error": "Plan not found"}

    # 统一 vid 格式，支持 "equipment:ZD02" 和 "ZD02" 两种传入形式
    normalized_vid = vid if vid.startswith("equipment:") else f"equipment:{vid}"

    # 1) 收集该车辆在 stages.team_actions 和 plan.car_actions 中的所有 car_action 资源 ID
    car_action_ids: List[str] = []
    seen_ca_ids = set()

    def _match_vid(ca_vid: Any) -> bool:
        if not ca_vid or not isinstance(ca_vid, str):
            return False
        return ca_vid == normalized_vid or ca_vid == vid

    for stage in plan.get("stages", []) or []:
        team_actions = stage.get("team_actions", {})
        car_actions_list = []
        if isinstance(team_actions, list):
            for entry in team_actions:
                car_actions_list.extend(entry.get("car_actions") or [])
                car_actions_list.extend(entry.get("team_actions") or [])
        elif isinstance(team_actions, dict):
            for vlist in team_actions.values():
                car_actions_list.extend(vlist or [])

        for ca in car_actions_list:
            if not _match_vid(ca.get("vid")):
                continue
            ca_rid = _normalize_car_action_resource_id(ca)
            if ca_rid and ca_rid not in seen_ca_ids:
                car_action_ids.append(ca_rid)
                seen_ca_ids.add(ca_rid)

    for ca in plan.get("car_actions", []) or []:
        if not _match_vid(ca.get("vid")):
            continue
        ca_rid = _normalize_car_action_resource_id(ca)
        if ca_rid and ca_rid not in seen_ca_ids:
            car_action_ids.append(ca_rid)
            seen_ca_ids.add(ca_rid)

    # 2) 级联删除每个 car_action
    deleted_action_ids = []
    deleted_car_action_ids = []
    for ca_rid in car_action_ids:
        result = _cascade_delete_resource(ca_rid, http_post, label=label)
        if result:
            deleted_car_action_ids.append(ca_rid)
            for deleted_id in result.get("deleted_resource_ids", []) or []:
                if deleted_id.startswith("action:") and deleted_id not in deleted_action_ids:
                    deleted_action_ids.append(deleted_id)
        else:
            print(f"[DELETE-VEHICLE] failed to cascade delete {ca_rid} from {label}, skip")

    # 3) 从文档中移除该车辆并直接 import 写回数据服务器
    updated_plan = copy.deepcopy(plan)
    for stage in updated_plan.get("stages", []) or []:
        team_actions = stage.get("team_actions", {})
        if isinstance(team_actions, list):
            for entry in team_actions:
                if entry.get("car_actions"):
                    entry["car_actions"] = [c for c in entry["car_actions"] if c.get("vid") != vid]
                if entry.get("team_actions"):
                    entry["team_actions"] = [c for c in entry["team_actions"] if c.get("vid") != vid]
        elif isinstance(team_actions, dict):
            for key in list(team_actions.keys()):
                team_actions[key] = [c for c in team_actions[key] if c.get("vid") != vid]
    updated_plan["car_actions"] = [c for c in updated_plan.get("car_actions", []) if c.get("vid") != vid]
    updated_plan["vehicle_summary"] = [v for v in updated_plan.get("vehicle_summary", []) if v.get("vid") != vid]
    updated_plan["updated_at"] = datetime.now(timezone.utc).isoformat()

    # 4) 写回数据服务器并更新本地缓存
    sync_ok = _import_plan_payload(rid, updated_plan, http_post, label=label)
    updated_plan["local_dirty"] = not sync_ok
    _cache_plan(rid, updated_plan, label)

    return {
        "ok": True,
        "plan_id": plan_id,
        "vid": vid,
        "deleted_actions": deleted_action_ids,
        "deleted_car_actions": deleted_car_action_ids,
        "sync_ok": sync_ok,
    }


def delete_vehicle_operator(plan_id: str, vid: str) -> Dict[str, Any]:
    """删除操控席方案中指定车辆的行动序列。"""
    return _delete_vehicle_from_plan(plan_id, vid, _http_post_operator, _http_get_operator, label="operator")


def delete_vehicle(plan_id: str, vid: str) -> Dict[str, Any]:
    """删除协同席方案中指定车辆的行动序列。"""
    return _delete_vehicle_from_plan(plan_id, vid, _http_post, _http_get, label="data_server")


def dispatch_plan_forward(plan_id: str, target_ips: List[str], timeout_seconds: int = 30) -> Dict[str, Any]:
    """协同席 — 将指定 plan 通过数据服务器 /ingestion/forward 下发到目标席位。

    席位 ID 先经 config.SEAT_TARGET_IPS 映射为目标数据服务器 IP（调试期间全部
    映射到操控席 25.11.1.56）；已是裸 IP 的值原样透传。
    返回包含数据服务器原始响应的 dict。
    """
    from app.config import SEAT_TARGET_IPS

    rid = plan_id if plan_id.startswith("plan:") else f"plan:{plan_id}"
    resolved = [SEAT_TARGET_IPS.get(t, t) for t in target_ips]
    result = forward_resources_to_targets(
        target_ips=resolved,
        resource_ids=[rid],
        timeout_seconds=timeout_seconds,
        silent=False,
    )
    if result is None:
        return {"ok": False, "error": "调用数据服务器 /ingestion/forward 失败"}
    if result.get("ok") is False:
        # DS HTTP 层错误（如未知席位 ID），透传详情
        return {"ok": False, "error": f"调用数据服务器 /ingestion/forward 失败: {result.get('error')}"}
    # DS 返回 200 也可能部分/全部目标失败，把失败详情透传给前端
    failed = [d for d in (result.get("details") or []) if d.get("failed_targets")]
    if failed:
        msgs = "; ".join(f"{d.get('resource_id')}: {d.get('message') or d.get('status')}" for d in failed)
        return {"ok": False, "error": f"部分目标下发失败: {msgs}", "forward_result": result}
    return {"ok": True, "plan_id": plan_id, "target_ips": resolved, "forward_result": result}


# ==================== Zenoh plan 变化通知订阅 ====================

PLAN_UPDATE_TOPIC = "op/pool/task/plan/update"
PLAN_COUNT_TOPIC = "op/pool/task/plan/count"
PLAN_SSE_SCOPE = "action_sequence"


def _push_plan_sse_event(event: str, data: Dict[str, Any]) -> None:
    """向 SSE 队列推送 plan 变化事件（线程安全，供 Zenoh 回调调用）。"""
    queues = sse_manager._overview_queues.get(PLAN_SSE_SCOPE, [])
    msg = {"event": event, "data": data}
    for q in list(queues):
        try:
            q.put_nowait(msg)
        except Exception:
            pass


def _parse_zenoh_payload(message: Dict[str, Any]) -> Dict[str, Any]:
    """从 Zenoh 消息中解析 payload，兼容 payload_text / payload 字段。"""
    payload = message.get("payload")
    if isinstance(payload, dict):
        return payload
    text = message.get("payload_text") or ""
    if isinstance(payload, str) and not text:
        text = payload
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def _on_plan_update(message: Dict[str, Any]) -> None:
    """处理 plan 内容变化通知：payload = {"plan_id": "<id>"}"""
    payload = _parse_zenoh_payload(message)
    plan_id = payload.get("plan_id")
    if not plan_id:
        return
    print(f"[AS-ZENOH] plan update received: plan_id={plan_id}")
    _push_plan_sse_event("action_sequence.plan.updated", {"plan_id": plan_id})


def _on_plan_count(message: Dict[str, Any]) -> None:
    """处理 plan 数量增删通知：payload = {"plan_id": "<id>", "operation": "add"|"delete"}"""
    payload = _parse_zenoh_payload(message)
    plan_id = payload.get("plan_id")
    operation = payload.get("operation")
    if not plan_id or operation not in ("add", "delete"):
        return
    print(f"[AS-ZENOH] plan count received: plan_id={plan_id}, operation={operation}")
    _push_plan_sse_event("action_sequence.plan.count_changed", {"plan_id": plan_id, "operation": operation})


def init_plan_change_subscription() -> bool:
    """订阅 plan 变化 Zenoh 主题，收到通知后通过 SSE 推送给前端。"""
    ok1 = zenoh_client.subscribe(PLAN_UPDATE_TOPIC, on_message=_on_plan_update)
    ok2 = zenoh_client.subscribe(PLAN_COUNT_TOPIC, on_message=_on_plan_count)
    if ok1 and ok2:
        print(f"[AS-ZENOH] subscribed plan change topics: {PLAN_UPDATE_TOPIC}, {PLAN_COUNT_TOPIC}")
    else:
        print(f"[AS-ZENOH] subscribe plan change topics failed: update={ok1}, count={ok2}")
    return ok1 and ok2


# ==================== 任务接收确认（task_received_status）→ SSE 推送 ====================

TASK_RECEIVED_TOPIC_SUFFIX = "/mission/task_received_status"


def _on_task_received_status(message: Dict[str, Any]) -> None:
    """车辆反馈监听器：任务接收确认（0x22230901）到达时通过 SSE 推送给前端。

    选择操控车辆时 subscribe_vehicle_feedbacks 已订阅对应车辆的
    op/t01/g01/v{vid}/mission/task_received_status topic，这里只负责把确认事件
    透传给前端，用于操控席行动序列详情的"方案已收到"发布状态提示。
    """
    topic = message.get("topic", "")
    if not topic.endswith(TASK_RECEIVED_TOPIC_SUFFIX):
        return
    payload = _parse_zenoh_payload(message)
    tid = payload.get("tid")
    if tid is None:
        return
    print(f"[AS-ZENOH] task_received_status: topic={topic} | tid={tid} | vehicle={payload.get('vehicle_id')}")
    _push_plan_sse_event("action_sequence.task_received", {
        "tid": tid,
        "vehicle_id": payload.get("vehicle_id") or "",
        "vmf": payload.get("VMF"),
        "recv_num": payload.get("recv_num"),
        "received_aids": payload.get("received_aids") or [],
        "topic": topic,
    })


def init_task_received_listener() -> None:
    """注册任务接收确认监听器（车辆反馈 topic 的订阅在 select-vehicle 时完成）。"""
    zenoh_client.register_feedback_listener(_on_task_received_status)


