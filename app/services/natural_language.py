"""将任务检测模型的结构化输出转换为中文自然语言。

转换过程使用确定性模板，不依赖外部大模型。入口函数既支持任务检测服务的
原始 HTTP 响应，也支持 ``docs/integrations/task-monitor.md`` 中定义的统一
``anomalies`` 响应。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Any


class DetectionType(str, Enum):
    """支持的检测结果类型。"""

    TASK_TIMEOUT = "TASK_TIMEOUT"
    ROUTE_TIMEOUT = "ROUTE_TIMEOUT"
    ROUTE_DEVIATION = "ROUTE_DEVIATION"
    ROUTE_CONFLICT = "ROUTE_CONFLICT"
    ROUTE_CONFLICT_PRECHECK = "ROUTE_CONFLICT_PRECHECK"
    ROUTE_CONFLICT_REALTIME = "ROUTE_CONFLICT_REALTIME"
    DEVIATION_HISTORY = "DEVIATION_HISTORY"
    CHECKIN_STATUS = "CHECKIN_STATUS"


_TYPE_ALIASES = {
    "/timeout/actions/status": DetectionType.TASK_TIMEOUT,
    "/monitor/check-timeout": DetectionType.ROUTE_TIMEOUT,
    "/monitor/check-deviation": DetectionType.ROUTE_DEVIATION,
    "/monitor/deviation-history": DetectionType.DEVIATION_HISTORY,
    "/conflict/detect": DetectionType.ROUTE_CONFLICT,
    "/conflict/validate": DetectionType.ROUTE_CONFLICT_PRECHECK,
    "/monitor/lookahead-warning": DetectionType.ROUTE_CONFLICT_REALTIME,
    "/monitor/checkin-status": DetectionType.CHECKIN_STATUS,
}

_TYPE_NAMES = {
    DetectionType.TASK_TIMEOUT: "行动超时",
    DetectionType.ROUTE_TIMEOUT: "路线点超时",
    DetectionType.ROUTE_DEVIATION: "路线偏离",
    DetectionType.DEVIATION_HISTORY: "路线偏离历史",
    DetectionType.ROUTE_CONFLICT: "路线冲突",
    DetectionType.ROUTE_CONFLICT_PRECHECK: "路线冲突预检",
    DetectionType.ROUTE_CONFLICT_REALTIME: "路线冲突临机预警",
    DetectionType.CHECKIN_STATUS: "路线点打卡",
}

_STATUS_NAMES = {
    "pending": "待执行",
    "in_progress": "执行中",
    "completed": "已完成",
    "failed": "执行失败",
}

_SEVERITY_NAMES = {
    "INFO": "提示",
    "WARNING": "警告",
    "ERROR": "严重",
    "CRITICAL": "紧急",
}


def detection_result_to_text(
    detector_type: DetectionType | str,
    result: Mapping[str, Any],
    *,
    plan_name: str | None = None,
) -> str:
    """把一次检测结果转换为可直接展示或播报的中文文本。

    Args:
        detector_type: 检测类型枚举、类型名称，或对应 HTTP 接口路径。
        result: 检测服务返回的 JSON 对象。
        plan_name: 可选的方案名称；提供后会添加到文本开头。

    Returns:
        完整的中文检测描述。多条结果使用换行分隔。

    Raises:
        TypeError: ``result`` 不是 JSON 对象或 Mapping。
        ValueError: 检测类型不受支持。
    """

    if not isinstance(result, Mapping):
        raise TypeError("result 必须是 JSON 对象或 Mapping")

    normalized_type = _normalize_type(detector_type)
    if "anomalies" in result:
        messages = _render_unified_result(normalized_type, result)
    else:
        renderer = _RENDERERS[normalized_type]
        messages = renderer(result)

    body = "\n".join(message for message in messages if message)
    if not body:
        body = f"{_TYPE_NAMES[normalized_type]}模型未返回可描述的结果。"
    if plan_name and plan_name.strip():
        return f"方案“{plan_name.strip()}”检测结果：\n{body}"
    return body


def _normalize_type(detector_type: DetectionType | str) -> DetectionType:
    if isinstance(detector_type, DetectionType):
        return detector_type
    if not isinstance(detector_type, str):
        raise ValueError(f"不支持的检测类型: {detector_type!r}")

    value = detector_type.strip()
    alias = _TYPE_ALIASES.get(value.lower())
    if alias is not None:
        return alias
    try:
        return DetectionType(value.upper())
    except ValueError as exc:
        supported = "、".join(item.value for item in DetectionType)
        raise ValueError(f"不支持的检测类型 {detector_type!r}；可选值：{supported}") from exc


def _render_unified_result(
    detector_type: DetectionType,
    result: Mapping[str, Any],
) -> list[str]:
    anomalies = _mapping_list(result.get("anomalies"))
    type_name = _TYPE_NAMES[detector_type]
    if not anomalies:
        return [f"{type_name}结果：未发现异常。"]

    messages = [f"{type_name}检测发现 {len(anomalies)} 项异常："]
    for index, anomaly in enumerate(anomalies, start=1):
        summary = str(anomaly.get("summary") or "").strip()
        severity = _SEVERITY_NAMES.get(
            str(anomaly.get("severity") or "WARNING").upper(),
            str(anomaly.get("severity") or "警告"),
        )
        if not summary:
            summary = _fallback_anomaly_summary(anomaly)
        messages.append(f"{index}. 【{severity}】{_ensure_period(summary)}")
    return messages


def _fallback_anomaly_summary(anomaly: Mapping[str, Any]) -> str:
    code = str(anomaly.get("code") or "UNKNOWN")
    subjects = _as_mapping(anomaly.get("subjects"))
    vehicles = _string_list(subjects.get("vehicle_ids"))
    actions = _string_list(subjects.get("action_ids"))
    subject_parts: list[str] = []
    if vehicles:
        subject_parts.append(f"车辆 {', '.join(vehicles)}")
    if actions:
        subject_parts.append(f"行动 {', '.join(actions)}")
    subject_text = "、".join(subject_parts) or "检测对象"
    return f"{subject_text}触发异常 {code}"


def _render_task_timeout(result: Mapping[str, Any]) -> list[str]:
    vehicles = _as_mapping(result.get("vehicles"))
    if not vehicles:
        return ["行动超时检测完成，未返回车辆行动数据。"]

    messages: list[str] = []
    for vehicle_id, raw_vehicle_result in vehicles.items():
        vehicle_result = _as_mapping(raw_vehicle_result)
        warnings = _mapping_list(vehicle_result.get("timeout_warnings"))
        if not warnings:
            messages.append(f"车辆 {vehicle_id} 当前没有行动超时。")
        for warning in warnings:
            action_seq = warning.get("action_seq", warning.get("action_id", "未知"))
            duration = _format_quantity(
                warning.get("timeout_duration", warning.get("overdue_seconds")), "秒"
            )
            status = _STATUS_NAMES.get(
                str(warning.get("status") or "").lower(),
                str(warning.get("status") or "未知"),
            )
            expected = _format_time(
                warning.get("expected_end_time", warning.get("end_time"))
            )
            messages.append(
                f"车辆 {vehicle_id} 的行动 {action_seq} 当前状态为“{status}”，"
                f"已超过预计完成时间 {duration}（预计完成时间：{expected}）。"
            )

        progress = _as_mapping(vehicle_result.get("progress"))
        if progress:
            completed = progress.get("completed", 0)
            total = progress.get("total", 0)
            percent = _format_number(progress.get("progress", 0), max_decimals=2)
            messages.append(
                f"车辆 {vehicle_id} 已完成 {completed}/{total} 项行动，当前进度为 {percent}%。"
            )
    return messages


def _render_route_conflict(result: Mapping[str, Any]) -> list[str]:
    conflicts = _mapping_list(result.get("conflicts"))
    if not conflicts:
        return ["指定时刻未发现车辆路线冲突。"]

    messages = [f"指定时刻发现 {len(conflicts)} 组车辆路线冲突："]
    for index, conflict in enumerate(conflicts, start=1):
        vehicle_a = conflict.get("vehicle_a", "未知车辆")
        vehicle_b = conflict.get("vehicle_b", "未知车辆")
        distance = _format_quantity(conflict.get("distance_m"), "米")
        messages.append(
            f"{index}. 车辆 {vehicle_a} 与车辆 {vehicle_b} 相距 {distance}，存在碰撞风险。"
        )
    return messages


def _render_route_conflict_precheck(result: Mapping[str, Any]) -> list[str]:
    intervals = _mapping_list(result.get("conflict_intervals"))
    if not intervals:
        return ["路线冲突预检完成，全时间轴内未发现冲突。"]

    messages = [f"路线冲突预检发现 {len(intervals)} 个冲突区间："]
    messages.extend(
        f"{index}. {_describe_conflict_interval(interval)}"
        for index, interval in enumerate(intervals, start=1)
    )
    return messages


def _render_route_conflict_realtime(result: Mapping[str, Any]) -> list[str]:
    warnings = _mapping_list(result.get("warnings"))
    if not warnings:
        return ["临机冲突检测完成，前瞻时间窗口内未发现冲突风险。"]

    interval_rows: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for warning in warnings:
        for interval in _mapping_list(warning.get("conflict_intervals")):
            pair = sorted(
                [str(interval.get("vehicle_a", "")), str(interval.get("vehicle_b", ""))]
            )
            key = (
                pair[0],
                pair[1],
                str(interval.get("t_start")),
                str(interval.get("t_end")),
            )
            if key not in seen:
                seen.add(key)
                interval_rows.append((warning, interval))

    if not interval_rows:
        return ["临机冲突检测返回了预警车辆，但未包含有效的冲突区间。"]

    messages = [f"临机冲突检测发现 {len(interval_rows)} 个冲突区间："]
    for index, (warning, interval) in enumerate(interval_rows, start=1):
        source_vehicle = warning.get("vehicle_id", "未知车辆")
        segment = warning.get("matched_segment_index", "未知")
        messages.append(
            f"{index}. 车辆 {source_vehicle} 的当前位置匹配到计划路线段 {segment}；"
            f"{_describe_conflict_interval(interval)}"
        )
    return messages


def _describe_conflict_interval(interval: Mapping[str, Any]) -> str:
    vehicle_a = interval.get("vehicle_a", "未知车辆")
    vehicle_b = interval.get("vehicle_b", "未知车辆")
    start = _format_time(interval.get("t_start"))
    end = _format_time(interval.get("t_end"))
    peak_distance = _format_quantity(interval.get("peak_distance_m"), "米")
    peak_time = _format_time(interval.get("peak_t"))
    return (
        f"车辆 {vehicle_a} 与车辆 {vehicle_b} 预计从 {start} 至 {end} 存在冲突，"
        f"最小距离为 {peak_distance}，风险最高时刻为 {peak_time}。"
    )


def _render_route_deviation(result: Mapping[str, Any]) -> list[str]:
    vehicle_id = result.get("vehicle_id", "未知车辆")
    distance = _format_quantity(result.get("distance_to_route_m"), "米")
    segment = result.get("matched_segment_index", "未知")
    timestamp = _format_time(result.get("timestamp"))
    if bool(result.get("is_deviated")):
        return [
            f"车辆 {vehicle_id} 在 {timestamp} 已偏离计划路线 {distance}，"
            f"最近匹配到计划路线段 {segment}。"
        ]
    return [
        f"车辆 {vehicle_id} 在 {timestamp} 距计划路线 {distance}，未发生路线偏离。"
    ]


def _render_deviation_history(result: Mapping[str, Any]) -> list[str]:
    history = _mapping_list(result.get("history"))
    if not history:
        return ["未查询到路线偏离历史记录。"]

    deviated = [item for item in history if bool(item.get("is_deviated"))]
    if not deviated:
        return [f"共检查 {len(history)} 条历史位置记录，均未发生路线偏离。"]

    messages = [
        f"共检查 {len(history)} 条历史位置记录，其中 {len(deviated)} 条发生路线偏离："
    ]
    for index, item in enumerate(deviated, start=1):
        vehicle_id = item.get("vehicle_id", "未知车辆")
        timestamp = _format_time(item.get("timestamp"))
        distance = _format_quantity(item.get("distance_to_route_m"), "米")
        segment = item.get("matched_segment_index", "未知")
        messages.append(
            f"{index}. 车辆 {vehicle_id} 在 {timestamp} 偏离计划路线 {distance}，"
            f"最近匹配到计划路线段 {segment}。"
        )
    return messages


def _render_route_timeout(result: Mapping[str, Any]) -> list[str]:
    if not bool(result.get("timeout")):
        vehicle_id = result.get("vehicle_id")
        subject = f"车辆 {vehicle_id}" if vehicle_id else "车辆"
        return [f"{subject}当前没有路线点到达超时。"]

    timeout_result = _as_mapping(result.get("result"))
    vehicle_id = timeout_result.get("vehicle_id", result.get("vehicle_id", "未知车辆"))
    point_index = timeout_result.get("overdue_point_index", "未知")
    duration = _format_quantity(timeout_result.get("overdue_seconds"), "秒")
    expected = _format_time(timeout_result.get("expected_arrival_time"))
    current = _format_time(timeout_result.get("current_time"))
    return [
        f"车辆 {vehicle_id} 未按时到达路线点 {point_index}，已超时 {duration}；"
        f"预计到达时间为 {expected}，当前时间为 {current}。"
    ]


def _render_checkin_status(result: Mapping[str, Any]) -> list[str]:
    vehicle_id = result.get("vehicle_id", "未知车辆")
    checked = _value_list(result.get("checked_in_indices"))
    skipped = _value_list(result.get("skipped_indices"))
    next_index = result.get("next_index")
    total = result.get("total_points", 0)
    if next_index is None or _is_complete_index(next_index, total):
        progress_text = f"已完成全部 {total} 个路线点打卡"
    else:
        progress_text = f"已打卡 {len(checked)}/{total} 个路线点，下一个待打卡点为 {next_index}"
    message = f"车辆 {vehicle_id} {progress_text}。"
    if skipped:
        indices = "、".join(str(item) for item in skipped)
        message += f"其中路线点 {indices} 为超时打卡。"
    return [message]


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not _is_sequence(value):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _value_list(value)]


def _value_list(value: Any) -> list[Any]:
    if not _is_sequence(value):
        return []
    return list(value)


def _is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_complete_index(next_index: Any, total: Any) -> bool:
    try:
        return int(next_index) >= int(total)
    except (TypeError, ValueError):
        return False


def _format_quantity(value: Any, unit: str) -> str:
    if value is None:
        return f"未知{unit}"
    return f"{_format_number(value, max_decimals=2)} {unit}"


def _format_number(value: Any, *, max_decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not isfinite(number):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{max_decimals}f}".rstrip("0").rstrip(".")


def _format_time(value: Any) -> str:
    if value is None:
        return "未知时间"
    if isinstance(value, str):
        return value.strip() or "未知时间"
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return str(value)
    if isfinite(timestamp) and abs(timestamp) >= 1_000_000_000:
        try:
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except (OverflowError, OSError, ValueError):
            pass
    return f"T={_format_number(value, max_decimals=3)} 秒"


def _ensure_period(text: str) -> str:
    return text if text.endswith(("。", "！", "？", ".", "!", "?")) else f"{text}。"


_RENDERERS = {
    DetectionType.TASK_TIMEOUT: _render_task_timeout,
    DetectionType.ROUTE_TIMEOUT: _render_route_timeout,
    DetectionType.ROUTE_DEVIATION: _render_route_deviation,
    DetectionType.DEVIATION_HISTORY: _render_deviation_history,
    DetectionType.ROUTE_CONFLICT: _render_route_conflict,
    DetectionType.ROUTE_CONFLICT_PRECHECK: _render_route_conflict_precheck,
    DetectionType.ROUTE_CONFLICT_REALTIME: _render_route_conflict_realtime,
    DetectionType.CHECKIN_STATUS: _render_checkin_status,
}
