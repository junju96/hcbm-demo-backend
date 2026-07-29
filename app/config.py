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
ZENOH_ROUTER_URL = "tcp/25.11.1.147:7447"

# ========== 本地服务 ==========
# 后端 HTTP 服务端口
BACKEND_PORT = 28600

# 前端开发服务器端口
FRONTEND_PORT = 5173


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
