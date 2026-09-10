"""
服务地址集中配置

所有外部服务地址统一定义在此文件中，便于查找和修改。
修改后需重启后端服务生效。
"""

# ========== 数据服务器 ==========
# 协同席数据服务器（PLAN / KILL_CHAIN / ACTION 等）
DATA_SERVER_BASE_URL = "http://25.11.1.178:28801"

# 操控席数据服务器（操控端 PLAN / ACTION / CAR_ACTIONS 等）
OPERATOR_DATA_SERVER_BASE_URL = "http://25.11.1.56:28801"

# 资源池服务（在线车辆、装备资源）
RESOURCE_POOL_BASE_URL = "http://25.11.1.178:28800"

# ========== 车辆相关服务 ==========
# 上游车辆管理服务（/vehicle/info/all 车辆实时信息）
VEHICLE_INFO_ALL_BASE_URL = "http://25.11.1.147:28410"

# 车辆控制服务（/user/current、/health 等）
VEHICLE_CONTROL_BASE_URL = "http://25.11.1.178:28009"

# ========== Zenoh 消息服务 ==========
# Zenoh 路由器地址（TCP）
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
# 调试期间席位 1/2/3 统一下发到操控席数据服务器（25.11.1.56，DS 默认端口 28801）。
# "ck"（车长席）→ 操控车数据服务器 25.11.1.3（端口同 DS 默认 28801，由 DS forward 机制处理）。
# 注意：DS 只接受裸 IP 或已注册席位 ID，不接受 ip:port 格式。
SEAT_TARGET_IPS = {
    "1": "25.11.1.56",
    "2": "25.11.1.56",
    "3": "25.11.1.56",
    "ck": "25.11.1.3",
}


def get_data_server_url() -> str:
    """获取协同席数据服务器地址"""
    return DATA_SERVER_BASE_URL


def get_operator_data_server_url() -> str:
    """获取操控席数据服务器地址"""
    return OPERATOR_DATA_SERVER_BASE_URL


def get_resource_pool_url() -> str:
    """获取资源池服务地址"""
    return RESOURCE_POOL_BASE_URL


def get_vehicle_info_all_url() -> str:
    """获取上游车辆管理服务地址"""
    return VEHICLE_INFO_ALL_BASE_URL


def get_vehicle_control_url() -> str:
    """获取车辆控制服务地址"""
    return VEHICLE_CONTROL_BASE_URL


def get_zenoh_router_url() -> str:
    """获取 Zenoh 路由器地址"""
    return ZENOH_ROUTER_URL
