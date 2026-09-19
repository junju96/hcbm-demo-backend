"""
服务地址集中配置

所有外部服务地址统一定义在此文件中，便于查找和修改。
模块常量即默认值；现场调试可通过 /api/v1/debug/config 接口写入
runtime_config.json（backend-dev 根目录，已 gitignore）覆盖，getter 每次
调用都读覆盖值，HTTP 地址类配置无需重启即可生效；Zenoh 路由器地址例外
（生效配置在 zenoh_py/zenoh.json5，改后需重启后端）。
"""

import copy
import ipaddress
import json
import os
from typing import Any, Dict, List

# ========== 数据服务器 ==========
# 协同席数据服务器（PLAN / KILL_CHAIN / ACTION 等）
DATA_SERVER_BASE_URL = "http://25.11.1.178:28801"

# 操控席数据服务器（操控端 PLAN / ACTION / CAR_ACTIONS 等）
OPERATOR_DATA_SERVER_BASE_URL = "http://25.11.1.56:28801"

# 资源池服务（在线车辆、装备资源）
RESOURCE_POOL_BASE_URL = "http://25.11.1.178:28800"

# ========== 车辆相关服务 ==========
# 上游车辆管理服务（/vehicle/info/all 车辆实时信息、/formation/mission/send 编队任务下发）
VEHICLE_INFO_ALL_BASE_URL = "http://25.11.1.3:28410"

# 车辆控制服务（/user/current、/health 等）
VEHICLE_CONTROL_BASE_URL = "http://25.11.1.178:28009"

# ========== Zenoh 消息服务 ==========
# Zenoh 路由器地址（TCP）。
# 注意：本常量无调用方（死配置），实际生效地址在 zenoh_py/zenoh.json5 的
# connect.endpoints，由 zenoh_py/zenoh_service.py 在启动时加载；改动时两处同步改。
ZENOH_ROUTER_URL = "tcp/25.11.1.3:7447"

# ========== 任务监控 ==========
# 任务监控总开关：False 时关闭所有状态监控的检测和上报——
# 下发时的超时注册/路线注册/冲突预检、执行后的 4 个轮询接口全部不调用。
# 后续要恢复时改回 True 并重启后端即可（细分开关见下面两项）。
MONITORING_ENABLED = False

# 发布/下发时的路线冲突预检（POST /conflict/validate）开关：
# False 时下发不再调用预检接口，也不产生预检预警弹窗。后续要恢复时改回 True 并重启。
MONITORING_PRECHECK_ENABLED = True

# 发布/下发时的路线注册（POST /conflict/vehicles）开关：
# False 时不再向监控服务注册路线（避免污染全局路线注册表）。恢复时改回 True 并重启。
MONITORING_ROUTE_REGISTER_ENABLED = True

# ========== 本地服务 ==========
# 后端 HTTP 服务端口
BACKEND_PORT = 28600

# 前端开发服务器端口
FRONTEND_PORT = 5173


# ========== 席位下发映射 ==========
# 协同席"下发"按钮（/ingestion/forward）的席位 ID → 目标数据服务器 IP 映射。
# 调试期间席位 1/2/3/4 统一下发到操控席数据服务器（25.11.1.56，DS 默认端口 28801）。
# "ck"（车长席）→ 操控车数据服务器 25.11.1.3（端口同 DS 默认 28801，由 DS forward 机制处理）。
# 注意：DS 只接受裸 IP 或已注册席位 ID，不接受 ip:port 格式；新增席位 4 需 DS 侧同步注册。
SEAT_TARGET_IPS = {
    "1": "25.11.1.56",
    "2": "25.11.1.56",
    "3": "25.11.1.56",
    "4": "25.11.1.56",
    "ck": "25.11.1.3",
}


# ========== 运行时配置覆盖 ==========
# 覆盖表持久化文件（backend-dev 根目录；现场二进制部署时放二进制同级可写目录）。
RUNTIME_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "runtime_config.json",
)

# 可覆盖键：key -> (中文名, 校验类型)
_OVERRIDABLE_KEYS: Dict[str, tuple] = {
    "DATA_SERVER_BASE_URL": ("协同席数据服务器", "url"),
    "OPERATOR_DATA_SERVER_BASE_URL": ("操控席数据服务器", "url"),
    "RESOURCE_POOL_BASE_URL": ("资源池服务", "url"),
    "VEHICLE_INFO_ALL_BASE_URL": ("车辆管理服务（/vehicle/info/all、编队任务下发）", "url"),
    "VEHICLE_CONTROL_BASE_URL": ("车辆控制服务", "url"),
    "SEAT_TARGET_IPS": ("席位下发目标 IP 映射", "seat_ips"),
}


def _load_runtime_overrides() -> Dict[str, Any]:
    """启动时从 runtime_config.json 读取覆盖表；文件不存在或损坏时返回空表"""
    try:
        with open(RUNTIME_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k in _OVERRIDABLE_KEYS}
    except (OSError, ValueError):
        pass
    return {}


_RUNTIME_OVERRIDES: Dict[str, Any] = _load_runtime_overrides()


def _effective(key: str) -> Any:
    """覆盖值优先，否则取同名模块常量默认值"""
    if key in _RUNTIME_OVERRIDES:
        return _RUNTIME_OVERRIDES[key]
    return globals()[key]


def get_runtime_overrides() -> Dict[str, Any]:
    """返回当前覆盖表（内存与 runtime_config.json 一致）"""
    return copy.deepcopy(_RUNTIME_OVERRIDES)


def _validate_override(key: str, value: Any) -> None:
    meta = _OVERRIDABLE_KEYS.get(key)
    if meta is None:
        raise ValueError(f"{key}: 不支持覆盖的配置项（可覆盖: {', '.join(_OVERRIDABLE_KEYS)}）")
    kind = meta[1]
    if kind == "url":
        if not isinstance(value, str) or not value.startswith(("http://", "https://")):
            raise ValueError(f"{key}: 必须是以 http:// 或 https:// 开头的 URL")
    elif kind == "seat_ips":
        if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise ValueError(f"{key}: 必须是 dict[str, str]（席位 ID → 裸 IP）")
        for k, v in value.items():
            try:
                ipaddress.ip_address(v)
            except ValueError:
                raise ValueError(f"{key}[{k}]: '{v}' 不是合法的裸 IP（不允许带端口/协议）")


def update_runtime_overrides(patch: Dict[str, Any]) -> Dict[str, Any]:
    """校验并合并覆盖项，写回 runtime_config.json 并更新内存，返回生效后的覆盖表。

    值为空字符串表示删除该键（恢复默认值），不做校验。
    校验失败抛 ValueError（信息指明字段），此时不落盘、不改内存。
    """
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是 dict")
    deletes = [k for k, v in patch.items() if v == ""]
    for key, value in patch.items():
        if value == "":
            if key not in _OVERRIDABLE_KEYS:
                raise ValueError(f"{key}: 不支持覆盖的配置项（可覆盖: {', '.join(_OVERRIDABLE_KEYS)}）")
            continue
        _validate_override(key, value)
    for key in deletes:
        _RUNTIME_OVERRIDES.pop(key, None)
    for key, value in patch.items():
        if value != "":
            _RUNTIME_OVERRIDES[key] = copy.deepcopy(value)
    with open(RUNTIME_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(_RUNTIME_OVERRIDES, f, ensure_ascii=False, indent=2)
    return copy.deepcopy(_RUNTIME_OVERRIDES)


def get_effective_config() -> List[Dict[str, Any]]:
    """返回 [{key, label, default, effective, overridden}]，供调试接口展示"""
    items = []
    for key, (label, _kind) in _OVERRIDABLE_KEYS.items():
        default = globals()[key]
        overridden = key in _RUNTIME_OVERRIDES
        items.append({
            "key": key,
            "label": label,
            "default": copy.deepcopy(default),
            "effective": copy.deepcopy(_RUNTIME_OVERRIDES[key]) if overridden else copy.deepcopy(default),
            "overridden": overridden,
        })
    return items


def get_data_server_url() -> str:
    """获取协同席数据服务器地址"""
    return _effective("DATA_SERVER_BASE_URL")


def get_operator_data_server_url() -> str:
    """获取操控席数据服务器地址"""
    return _effective("OPERATOR_DATA_SERVER_BASE_URL")


def get_resource_pool_url() -> str:
    """获取资源池服务地址"""
    return _effective("RESOURCE_POOL_BASE_URL")


def get_vehicle_info_all_url() -> str:
    """获取上游车辆管理服务地址"""
    return _effective("VEHICLE_INFO_ALL_BASE_URL")


def get_vehicle_control_url() -> str:
    """获取车辆控制服务地址"""
    return _effective("VEHICLE_CONTROL_BASE_URL")


def get_formation_mission_send_url() -> str:
    """编队机动任务下发接口（POST，body 为 {"task": ...}，替代原 zenoh send_formation_mission）"""
    return f"{get_vehicle_info_all_url()}/formation/mission/send"


def get_seat_target_ips() -> Dict[str, str]:
    """获取席位 ID → 目标数据服务器 IP 映射"""
    return dict(_effective("SEAT_TARGET_IPS"))


def get_zenoh_router_url() -> str:
    """获取 Zenoh 路由器地址（死配置，实际生效值见 zenoh_py/zenoh.json5）"""
    return ZENOH_ROUTER_URL
