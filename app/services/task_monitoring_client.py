"""
任务监控服务客户端

职责：
  1. 在操控席任务下发成功后，调用任务监控服务（25.11.1.178:28509）的黄色接口：
     - POST /timeout/init-monitor          注册车辆+行动（任务超时检测）
     - POST /conflict/vehicles             注册路线（路线冲突检测）
     - POST /conflict/validate             出发前预检冲突
  2. 在任务开始执行后，每 5 秒调用一次绿色接口：
     - POST /timeout/actions/status        上报行动状态，返回预警与进度
     - POST /monitor/report-position       上报车辆实时位置
     - POST /monitor/lookahead-warn        临机预警
     - POST /monitor/check-deviation       查是否偏离
  3. 仅针对当前操控席已连接并操控的单车，不涉及多车。

约束：
  - 所有上报参数严格从行动序列任务数据中读取，不做兜底。
  - 若任务数据中缺少必要字段，记录警告并继续（接口必填字段用 0/默认值占位，便于排查）。
  - 绿色接口的返回值只解析、打印，后续业务逻辑待定。
"""

import json
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.services import vehicle_control_client
from app.services.natural_language import DetectionType, detection_result_to_text


# ---------- 配置 ----------

TASK_MONITORING_BASE_URL = "http://25.11.1.178:28509"
POLL_INTERVAL_SECONDS = 5.0
REQUEST_TIMEOUT_SECONDS = 5

WARNING_SERVICE_BASE_URL = "http://25.11.1.147:28478"
WARNING_SERVICE_PATH = "/monitor/task"
WARNING_REQUEST_TIMEOUT_SECONDS = 3

_SOURCE_TO_DETECTION_TYPE = {
    "/timeout/actions/status": DetectionType.TASK_TIMEOUT,
    "/conflict/validate": DetectionType.ROUTE_CONFLICT_PRECHECK,
    "/monitor/lookahead-warning": DetectionType.ROUTE_CONFLICT_REALTIME,
    "/monitor/check-deviation": DetectionType.ROUTE_DEVIATION,
}

_WARNING_TYPES = {
    DetectionType.TASK_TIMEOUT: "task_deviation",
    DetectionType.ROUTE_CONFLICT_PRECHECK: "route_conflict",
    DetectionType.ROUTE_CONFLICT_REALTIME: "route_conflict",
    DetectionType.ROUTE_DEVIATION: "route_deviation",
}

# ---------- 日志 ----------


def _log(level: str, message: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    print(f"[{now}] [TM] [{level}] {message}")


# ---------- 基础 HTTP 调用 ----------


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """向任务监控服务发送 POST 请求，返回统一结构 {"ok", "status_code", "error", "data"}"""
    url = f"{TASK_MONITORING_BASE_URL}{path}"
    _log("DEBUG", f"POST {url} payload={json.dumps(payload, ensure_ascii=False)}")
    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT_SECONDS,
            proxies={"http": None, "https": None},
        )
        try:
            response_text = resp.text
        except Exception:
            response_text = ""
        _log("DEBUG", f"POST {url} status={resp.status_code} response_text={response_text}")
        resp.raise_for_status()
        try:
            data = resp.json()
        except Exception as json_exc:
            _log("WARN", f"POST {url} response is not valid JSON: {json_exc}")
            data = response_text
        result = {"ok": True, "status_code": resp.status_code, "error": None, "data": data}
        _log("DEBUG", f"POST {url} response={json.dumps(result, ensure_ascii=False)}")
        return result
    except requests.exceptions.Timeout as exc:
        _log("ERROR", f"POST {url} timeout: {exc}")
        return {"ok": False, "status_code": None, "error": "请求超时", "data": None}
    except requests.exceptions.ConnectionError as exc:
        _log("ERROR", f"POST {url} connection error: {exc}")
        return {"ok": False, "status_code": None, "error": f"连接失败: {exc}", "data": None}
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        try:
            body = exc.response.text if exc.response is not None else ""
        except Exception:
            body = ""
        _log("ERROR", f"POST {url} HTTP error status={status} body={body}")
        return {"ok": False, "status_code": status, "error": f"HTTP {status}: {body}", "data": None}
    except Exception as exc:
        _log("ERROR", f"POST {url} exception: {exc}")
        return {"ok": False, "status_code": None, "error": f"请求异常: {exc}", "data": None}


# ---------- 工具函数 ----------


def _clean_vid(vid: str) -> str:
    return (vid or "").replace("equipment:", "")


def _parse_timestamp(value: Any) -> Optional[float]:
    """把任务数据中的时间字符串解析为 Unix 时间戳（秒）。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    fmts = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.timestamp()
        except ValueError:
            continue
    _log("WARN", f"无法解析时间字符串: {value}")
    return None


def _parse_duration_seconds(value: Any) -> float:
    """把 HH:MM:SS 或秒数解析为秒。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    parts = text.split(":")
    try:
        if len(parts) == 3:
            h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
        if len(parts) == 2:
            m, s = int(parts[0]), float(parts[1])
            return m * 60 + s
        return float(text)
    except (ValueError, TypeError):
        _log("WARN", f"无法解析时长字符串: {value}")
        return 0.0


ROUTE_ACTION_TYPES = {
    "auto-move",
    "follow-move",
    "formation-move",
    "return-to-base",
}


def _extract_route_points(action: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从单个 route 类型 action 中提取路径点。"""
    param = action.get("param") or {}
    points: List[Dict[str, Any]] = []

    candidates = []
    if param.get("waypoints"):
        candidates = param["waypoints"]
    elif param.get("points"):
        candidates = param["points"]

    for pt in candidates:
        if not isinstance(pt, dict):
            continue
        lat = pt.get("lat") if pt.get("lat") is not None else pt.get("latitude")
        lon = pt.get("lon") if pt.get("lon") is not None else pt.get("longitude")
        alt = pt.get("alt") if pt.get("alt") is not None else pt.get("altitude", 0)
        if lat is None or lon is None:
            continue
        try:
            points.append({
                "lat": float(lat),
                "lon": float(lon),
                "alt": float(alt) if alt is not None else 0.0,
                "dwell_time": 0,
                "expected_arrival_time": 0,
            })
        except (ValueError, TypeError):
            continue
    return points


def _flatten_vehicle_actions(plan: Dict[str, Any], vehicle_id: str) -> List[Dict[str, Any]]:
    """按 stage_seq / action_seq 扁平化某车辆的全部 action。"""
    vid = _clean_vid(vehicle_id)
    actions: List[Dict[str, Any]] = []
    for vs in plan.get("vehicle_summary", []) or []:
        if _clean_vid(vs.get("vid")) != vid:
            continue
        for stage in vs.get("stages", []) or []:
            for action in stage.get("actions", []) or []:
                actions.append({**action, "stage_seq": stage.get("stage_seq", 0)})
    actions.sort(key=lambda a: (a.get("stage_seq", 0), a.get("action_seq", 0) or 0))
    return actions


def _map_action_status(state: Any) -> str:
    """把任务数据 / 运行时状态映射为任务监控服务状态枚举。"""
    text = str(state or "").strip().lower()
    if text in {"done", "completed", "success", "terminated", "stopped", "deleted"}:
        return "completed"
    if text in {"active", "paused", "in_progress", "executing"}:
        return "in_progress"
    if text in {"failed", "error"}:
        return "failed"
    return "pending"


# ---------- 告警去重工具 ----------


_sent_warning_signatures: Dict[str, set] = {}
_warning_lock = threading.Lock()


def clear_warning_signatures(plan_id: str, vehicle_id: str) -> None:
    key = _monitor_key(plan_id, vehicle_id)
    with _warning_lock:
        _sent_warning_signatures.pop(key, None)


def _as_mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _mapping_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, dict)]


def _extract_anomalies(
    source: str, data: Any, vehicle_id: str
) -> List[Tuple[Dict[str, Any], List[str]]]:
    """从监控接口返回体中提取异常，返回 (synthetic_result, action_ids) 列表。"""
    if source == "/timeout/actions/status":
        vehicles = _as_mapping(data.get("vehicles"))
        vehicle_data = _as_mapping(vehicles.get(vehicle_id))
        warnings = _mapping_list(vehicle_data.get("timeout_warnings"))
        progress = _as_mapping(vehicle_data.get("progress"))
        anomalies: List[Tuple[Dict[str, Any], List[str]]] = []
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            synthetic = {
                "vehicles": {vehicle_id: {"timeout_warnings": [warning], "progress": progress}}
            }
            action_ids = [str(warning.get("action_seq", warning.get("action_id", "")))]
            anomalies.append((synthetic, action_ids))
        return anomalies

    if source == "/conflict/validate":
        intervals = _mapping_list(data.get("conflict_intervals"))
        return [({"conflict_intervals": [interval]}, []) for interval in intervals if isinstance(interval, dict)]

    if source == "/monitor/lookahead-warning":
        warnings = _mapping_list(data.get("warnings"))
        anomalies: List[Tuple[Dict[str, Any], List[str]]] = []
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            source_vehicle = warning.get("vehicle_id", vehicle_id)
            matched_segment = warning.get("matched_segment_index")
            matched_lat = warning.get("matched_lat")
            matched_lon = warning.get("matched_lon")
            for interval in _mapping_list(warning.get("conflict_intervals")):
                if not isinstance(interval, dict):
                    continue
                synthetic_warning = {
                    "vehicle_id": source_vehicle,
                    "matched_segment_index": matched_segment,
                    "matched_lat": matched_lat,
                    "matched_lon": matched_lon,
                    "conflict_intervals": [interval],
                }
                anomalies.append(({"warnings": [synthetic_warning]}, []))
        return anomalies

    if source == "/monitor/check-deviation":
        if isinstance(data, dict) and data.get("is_deviated"):
            return [(dict(data), [])]
        return []

    return []


def _warning_signature(source: str, detection_type: DetectionType, synthetic: Dict[str, Any]) -> str:
    """
    生成预警去重签名。

    业务规则：
      - 任务超时（TASK_TIMEOUT）和路线偏离（ROUTE_DEVIATION）这两类提示信息，
        在同一个 plan/vehicle 的一次执行周期内只上报一次；plan 结束或中断后
        通过 stop_monitoring -> clear_warning_signatures 重置。
      - 路线冲突类保持原有细粒度签名，避免遗漏不同时间/不同车辆对的冲突。
    """
    if detection_type == DetectionType.TASK_TIMEOUT:
        vid = list(synthetic["vehicles"].keys())[0]
        return f"task_deviation:{vid}"

    if detection_type == DetectionType.ROUTE_DEVIATION:
        return f"route_deviation:{synthetic.get('vehicle_id', '')}"

    if detection_type == DetectionType.ROUTE_CONFLICT_PRECHECK:
        interval = synthetic["conflict_intervals"][0]
        pair = sorted([str(interval.get("vehicle_a", "")), str(interval.get("vehicle_b", ""))])
        return f"precheck:{pair[0]}:{pair[1]}:{interval.get('t_start', '')}:{interval.get('t_end', '')}"

    if detection_type == DetectionType.ROUTE_CONFLICT_REALTIME:
        interval = synthetic["warnings"][0]["conflict_intervals"][0]
        pair = sorted([str(interval.get("vehicle_a", "")), str(interval.get("vehicle_b", ""))])
        return f"realtime:{pair[0]}:{pair[1]}:{interval.get('t_start', '')}:{interval.get('t_end', '')}"

    return f"{source}:{json.dumps(synthetic, ensure_ascii=False, sort_keys=True)}"


# ---------- 提醒服务调用 ----------


def _send_warning(
    plan_id: str,
    vehicle_id: str,
    warning_type: str,
    action_ids: List[str],
    warning_content: str,
) -> Dict[str, Any]:
    warning_id = str(uuid.uuid4())
    payload = {
        "warning_id": warning_id,
        "monitor_report": {
            "plan_id": plan_id,
            "equipment_ids": [vehicle_id],
            "action_ids": action_ids,
            "warning_type": warning_type,
            "warning_content": warning_content,
        },
    }
    url = f"{WARNING_SERVICE_BASE_URL}{WARNING_SERVICE_PATH}"
    _log("DEBUG", f"POST {url} payload={json.dumps(payload, ensure_ascii=False)}")
    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=WARNING_REQUEST_TIMEOUT_SECONDS,
            proxies={"http": None, "https": None},
        )
        resp.raise_for_status()
        result = {"ok": True, "status_code": resp.status_code, "error": None, "data": resp.json()}
        _log("DEBUG", f"POST {url} response={json.dumps(result, ensure_ascii=False)}")
        return result
    except requests.exceptions.Timeout as exc:
        _log("ERROR", f"POST {url} timeout: {exc}")
        return {"ok": False, "status_code": None, "error": "请求超时", "data": None}
    except requests.exceptions.ConnectionError as exc:
        _log("ERROR", f"POST {url} connection error: {exc}")
        return {"ok": False, "status_code": None, "error": f"连接失败: {exc}", "data": None}
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        body = exc.response.text if exc.response is not None else ""
        _log("ERROR", f"POST {url} HTTP error status={status} body={body}")
        return {"ok": False, "status_code": status, "error": f"HTTP {status}: {body}", "data": None}
    except Exception as exc:
        _log("ERROR", f"POST {url} exception: {exc}")
        return {"ok": False, "status_code": None, "error": f"请求异常: {exc}", "data": None}


def send_warnings_if_any(
    plan_id: str,
    vehicle_id: str,
    source: str,
    result: Dict[str, Any],
    plan_name: Optional[str] = None,
) -> None:
    """如果监控接口结果包含异常，则发送提醒（去重）。"""
    if not isinstance(result, dict) or not result.get("ok") or not result.get("data"):
        return

    detection_type = _SOURCE_TO_DETECTION_TYPE.get(source)
    if detection_type is None:
        _log("WARN", f"unknown warning source {source}")
        return

    data = result["data"]
    anomalies = _extract_anomalies(source, data, vehicle_id)
    if not anomalies:
        return

    key = _monitor_key(plan_id, vehicle_id)
    with _warning_lock:
        sent = _sent_warning_signatures.setdefault(key, set())

    warning_type = _WARNING_TYPES.get(detection_type, "unknown")
    for synthetic, action_ids in anomalies:
        signature = _warning_signature(source, detection_type, synthetic)
        with _warning_lock:
            if signature in sent:
                _log(
                    "DEBUG",
                    f"warning already sent, skip: plan={plan_id} "
                    f"vehicle={vehicle_id} signature={signature}",
                )
                continue
            # 无论后续发送是否成功，同一类 warning 在本次 plan 执行周期内只尝试一次
            sent.add(signature)

        text = detection_result_to_text(detection_type, synthetic, plan_name=plan_name)
        _send_warning(plan_id, vehicle_id, warning_type, action_ids, text)


# ---------- 黄色接口：任务下发成功后调用 ----------


def init_timeout_monitor(plan_id: str, vehicle_id: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    POST /timeout/init-monitor
    注册全部车辆+行动，所有行动状态初始化为 pending。
    """
    vid = _clean_vid(vehicle_id)
    actions = _flatten_vehicle_actions(plan, vid)
    monitor_actions = []
    for action in actions:
        param = action.get("param") or {}
        start_ts = _parse_timestamp(param.get("start_time"))
        duration = _parse_duration_seconds(param.get("mission_duration"))
        end_ts = start_ts + duration if start_ts is not None else 0.0
        monitor_actions.append({
            "action_seq": action.get("action_seq") or action.get("action_id"),
            "start_time": start_ts if start_ts is not None else 0.0,
            "end_time": end_ts,
            "description": action.get("name", ""),
        })

    payload = {"vehicles": {vid: monitor_actions}}
    result = _post("/timeout/init-monitor", payload)
    _log("INFO", f"init-timeout-monitor plan={plan_id} vehicle={vid} actions={len(monitor_actions)} ok={result['ok']}")
    return result


def register_route(vehicle_id: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    POST /conflict/vehicles
    注册单车路线。只拼接 route 类型 action 的 waypoints/points。
    不同 route action 之间需要补充连接段速度，默认使用上一 action 最后一段速度。
    """
    vid = _clean_vid(vehicle_id)
    actions = _flatten_vehicle_actions(plan, vid)

    all_points: List[Dict[str, Any]] = []
    segment_speeds: List[float] = []
    prev_speed: Optional[float] = None

    for action in actions:
        action_type = (action.get("action_type") or "").lower()
        if action_type not in ROUTE_ACTION_TYPES:
            continue
        pts = _extract_route_points(action)
        if len(pts) < 2:
            continue
        speed = action.get("param", {}).get("limited_speed", 0)
        try:
            speed_val = float(speed) if speed is not None else 0.0
        except (ValueError, TypeError):
            speed_val = 0.0

        # 非第一个 route action 时，补充与上一个 action 末点之间的连接段速度
        if all_points and prev_speed is not None:
            segment_speeds.append(prev_speed)

        all_points.extend(pts)
        segment_speeds.extend([speed_val] * (len(pts) - 1))
        prev_speed = speed_val

    payload = {
        "vehicle_id": vid,
        "points": all_points,
        "departure_time": 0,
        "segment_speeds": segment_speeds,
    }
    result = _post("/conflict/vehicles", payload)
    _log("INFO", f"register-route vehicle={vid} points={len(all_points)} segments={len(segment_speeds)} ok={result['ok']}")
    return result


def validate_route(distance_threshold_m: float = 2.0, sample_interval_s: float = 0.5) -> Dict[str, Any]:
    """
    POST /conflict/validate
    出发前预检冲突。
    """
    payload = {
        "distance_threshold_m": distance_threshold_m,
        "sample_interval_s": sample_interval_s,
    }
    result = _post("/conflict/validate", payload)
    _log("INFO", f"validate-route ok={result['ok']}")
    return result


def register_mission_for_monitoring(plan_id: str, vehicle_id: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    任务下发成功后一次性调用：注册超时检测 + 注册路线 + 预检冲突。
    返回三个接口的原始结果，便于前端或日志查看。
    """
    timeout_result = init_timeout_monitor(plan_id, vehicle_id, plan)
    route_result = register_route(vehicle_id, plan)
    validate_result = validate_route()
    return {
        "timeout_init": timeout_result,
        "route_register": route_result,
        "route_validate": validate_result,
    }


# ---------- 绿色接口：任务开始执行后每 5 秒调用 ----------


def report_action_status(vehicle_id: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    POST /timeout/actions/status
    上报当前各 action 状态，返回超时预警和完成进度。
    """
    vid = _clean_vid(vehicle_id)
    actions = _flatten_vehicle_actions(plan, vid)
    now = time.time()
    status_list = []
    for action in actions:
        status_list.append({
            "action_seq": action.get("action_seq") or action.get("action_id"),
            "status": _map_action_status(action.get("state")),
            "update_time": now,
        })
    payload = {"vehicles": {vid: status_list}}
    result = _post("/timeout/actions/status", payload)
    _log("INFO", f"report-action-status vehicle={vid} actions={len(status_list)} ok={result['ok']}")
    return result


def _get_vehicle_position(vehicle_id: str) -> Optional[Dict[str, float]]:
    """从车辆控制服务缓存读取车辆当前位置。"""
    vid = _clean_vid(vehicle_id)
    info = vehicle_control_client.get_vehicle_info(vid)
    if info is None:
        vehicle_control_client.refresh_vehicle_info()
        info = vehicle_control_client.get_vehicle_info(vid)
    if not info:
        return None

    lat = info.get("lat") or info.get("latitude")
    lon = info.get("lon") or info.get("longitude")
    heading = info.get("heading") or info.get("heading_deg")
    speed = info.get("speed") or info.get("speed_ms")
    try:
        return {
            "lat": float(lat) if lat is not None else 0.0,
            "lon": float(lon) if lon is not None else 0.0,
            "heading_deg": float(heading) if heading is not None else 0.0,
            "speed_ms": float(speed) if speed is not None else 0.0,
        }
    except (ValueError, TypeError):
        return None


def report_position(vehicle_id: str) -> Dict[str, Any]:
    """
    POST /monitor/report-position
    上报车辆实时位置。位置从车辆控制服务读取；读取不到时仍按接口要求发送 0 占位，并记录警告。
    """
    vid = _clean_vid(vehicle_id)
    pos = _get_vehicle_position(vid)
    if pos is None:
        _log("WARN", f"无法从车辆控制服务获取位置 vehicle={vid}")
        pos = {"lat": 0.0, "lon": 0.0, "heading_deg": 0.0, "speed_ms": 0.0}
    payload = {
        "vehicle_id": vid,
        "position": {
            "lat": pos["lat"],
            "lon": pos["lon"],
            "heading_deg": pos["heading_deg"],
            "speed_ms": pos["speed_ms"],
        },
        "timestamp": time.time(),
    }
    result = _post("/monitor/report-position", payload)
    _log("INFO", f"report-position vehicle={vid} ok={result['ok']}")
    return result


def lookahead_warning(
    timestamp: Optional[float] = None,
    lookahead_seconds: float = 30.0,
    distance_threshold_m: float = 2.0,
    sample_interval_s: float = 0.5,
) -> Dict[str, Any]:
    """
    POST /monitor/lookahead-warning
    临机预警。
    """
    payload = {
        "timestamp": timestamp if timestamp is not None else time.time(),
        "lookahead_seconds": lookahead_seconds,
        "distance_threshold_m": distance_threshold_m,
        "sample_interval_s": sample_interval_s,
    }
    result = _post("/monitor/lookahead-warning", payload)
    _log("INFO", f"lookahead-warning ok={result['ok']}")
    return result


def check_deviation(vehicle_id: str, threshold_m: float = 10.0) -> Dict[str, Any]:
    """
    POST /monitor/check-deviation
    检查车辆是否偏离任务路线。
    """
    vid = _clean_vid(vehicle_id)
    payload = {"vehicle_id": vid, "threshold_m": threshold_m}
    result = _post("/monitor/check-deviation", payload)
    _log("INFO", f"check-deviation vehicle={vid} ok={result['ok']}")
    return result


# ---------- 轮询管理 ----------

_active_timers: Dict[str, threading.Timer] = {}
_active_lock = threading.Lock()


def _monitor_key(plan_id: str, vehicle_id: str) -> str:
    return f"{plan_id}#{_clean_vid(vehicle_id)}"


def _is_mission_finished(status_result: Dict[str, Any], vehicle_id: str) -> bool:
    """
    根据 /timeout/actions/status 返回值判断任务是否已全部结束。
    判定依据：progress.completed >= progress.total 且 total > 0。
    """
    if not status_result.get("ok") or not status_result.get("data"):
        return False
    try:
        vid = _clean_vid(vehicle_id)
        vehicles = status_result["data"].get("vehicles", {})
        vehicle_data = vehicles.get(vid, {})
        progress = vehicle_data.get("progress", {})
        completed = progress.get("completed", 0)
        total = progress.get("total", 0)
        return total > 0 and completed >= total
    except Exception:
        return False


def _poll_once(plan_id: str, vehicle_id: str, plan: Dict[str, Any]) -> None:
    """单次轮询：调用所有绿色接口；若任务已全部完成则自动停止轮询。"""
    status_result = report_action_status(vehicle_id, plan)
    send_warnings_if_any(
        plan_id, vehicle_id, "/timeout/actions/status", status_result,
        plan_name=plan.get("title"),
    )

    # 如果所有行动都已完成，自动停止后续轮询
    if _is_mission_finished(status_result, vehicle_id):
        _log("INFO", f"mission finished plan={plan_id} vehicle={vehicle_id}, stopping monitor")
        stop_monitoring(plan_id, vehicle_id)
        return

    report_position(vehicle_id)
    lookahead_result = lookahead_warning()
    send_warnings_if_any(
        plan_id, vehicle_id, "/monitor/lookahead-warning", lookahead_result,
        plan_name=plan.get("title"),
    )
    deviation_result = check_deviation(vehicle_id)
    send_warnings_if_any(
        plan_id, vehicle_id, "/monitor/check-deviation", deviation_result,
        plan_name=plan.get("title"),
    )


def _schedule_next(plan_id: str, vehicle_id: str, plan: Dict[str, Any]) -> None:
    """调度下一次轮询。"""
    key = _monitor_key(plan_id, vehicle_id)
    with _active_lock:
        if key not in _active_timers:
            return
    timer = threading.Timer(POLL_INTERVAL_SECONDS, _poll_cycle, args=(plan_id, vehicle_id, plan))
    timer.daemon = True
    with _active_lock:
        _active_timers[key] = timer
    timer.start()


def _poll_cycle(plan_id: str, vehicle_id: str, plan: Dict[str, Any]) -> None:
    """轮询周期函数。"""
    key = _monitor_key(plan_id, vehicle_id)
    with _active_lock:
        if key not in _active_timers:
            return
    try:
        _poll_once(plan_id, vehicle_id, plan)
    except Exception as exc:
        _log("ERROR", f"poll-cycle error plan={plan_id} vehicle={vehicle_id}: {exc}")
    finally:
        _schedule_next(plan_id, vehicle_id, plan)


def start_monitoring(plan_id: str, vehicle_id: str, plan: Dict[str, Any]) -> None:
    """任务开始执行后启动 5 秒轮询。"""
    key = _monitor_key(plan_id, vehicle_id)
    stop_monitoring(plan_id, vehicle_id)
    with _active_lock:
        _active_timers[key] = None  # 占位，防止竞态
    _log("INFO", f"start monitoring plan={plan_id} vehicle={vehicle_id}")
    # 使用 Timer 在后台线程中执行，避免阻塞 FastAPI 事件循环
    timer = threading.Timer(POLL_INTERVAL_SECONDS, _poll_cycle, args=(plan_id, vehicle_id, plan))
    timer.daemon = True
    with _active_lock:
        _active_timers[key] = timer
    timer.start()


def stop_monitoring(plan_id: str, vehicle_id: str) -> None:
    """停止指定方案/车辆的轮询。"""
    key = _monitor_key(plan_id, vehicle_id)
    with _active_lock:
        timer = _active_timers.pop(key, None)
    clear_warning_signatures(plan_id, vehicle_id)
    if timer:
        timer.cancel()
        _log("INFO", f"stop monitoring plan={plan_id} vehicle={vehicle_id}")


def is_monitoring(plan_id: str, vehicle_id: str) -> bool:
    key = _monitor_key(plan_id, vehicle_id)
    with _active_lock:
        return key in _active_timers
