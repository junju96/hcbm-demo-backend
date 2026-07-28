"""
车辆控制服务客户端
维护从 vehicle_control_service (默认 http://25.11.1.2:28430) 获取的在线车辆信息缓存。

职责：
  1. 提供 query_vehicle_info_all() 拉取 /vehicle/info/all
  2. 维护内存缓存 _VEHICLE_INFO_CACHE: vehicle_id -> {VMF, ip, type, ...}
  3. 提供 get_vehicle_info(vehicle_id), get_vehicle_ip(vehicle_id), get_vehicle_vmf(vehicle_id)
  4. 提供 refresh_vehicle_info() 手动刷新
  5. 提供 get_connected_vehicle_ids() 获取当前已连接车辆列表

用法：
  from app.services.vehicle_control_client import get_vehicle_ip, get_vehicle_vmf, refresh_vehicle_info
"""

from typing import Any, Dict, List, Optional
import threading
import time

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# /vehicle/info/all 使用独立服务地址（上游车辆管理服务）
VEHICLE_INFO_ALL_BASE_URL = "http://25.11.1.147:28410"
# 其他接口（/user/current、/health 等）仍使用原车辆控制服务地址
VEHICLE_CONTROL_BASE_URL = "http://25.11.1.178:28009"
VEHICLE_INFO_ALL_PATH = "/vehicle/info/all"
DEFAULT_REFRESH_INTERVAL_SECONDS = 30

# vehicle_id -> vehicle_info dict
_VEHICLE_INFO_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_LAST_REFRESH_AT: Optional[float] = None


def _normalize_vehicle_id(vehicle_id: str) -> str:
    """去掉 equipment: 前缀，统一大小写"""
    if not vehicle_id:
        return vehicle_id
    return vehicle_id.replace("equipment:", "").strip()


def query_vehicle_info_all(
    base_url: str = VEHICLE_INFO_ALL_BASE_URL,
    timeout: int = 5,
) -> Optional[List[Dict[str, Any]]]:
    """向上游车辆管理服务查询所有车辆信息，返回原始数组"""
    if not HAS_REQUESTS:
        print("[VC-DEBUG] requests not available")
        return None
    url = f"{base_url}{VEHICLE_INFO_ALL_PATH}"
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            proxies={"http": None, "https": None},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items") or data.get("data") or []
        print(f"[VC-DEBUG] unexpected response type: {type(data)}")
        return None
    except Exception as e:
        print(f"[VC-DEBUG] query_vehicle_info_all failed: {e}")
        return None


def refresh_vehicle_info(
    base_url: str = VEHICLE_CONTROL_BASE_URL,
    timeout: int = 5,
) -> List[Dict[str, Any]]:
    """刷新车辆信息缓存，返回当前连接的车辆列表（vid 已去前缀）"""
    global _VEHICLE_INFO_CACHE, _LAST_REFRESH_AT
    items = query_vehicle_info_all(base_url, timeout)
    new_cache: Dict[str, Dict[str, Any]] = {}
    result: List[Dict[str, Any]] = []
    if items:
        for item in items:
            vid_raw = item.get("vehicle_id") or ""
            if not vid_raw:
                continue
            vid = _normalize_vehicle_id(vid_raw)
            # 保持原字段，同时提供统一访问
            normalized = dict(item)
            normalized["vehicle_id"] = vid
            normalized["vid"] = vid
            new_cache[vid] = normalized
            result.append(normalized)
    with _CACHE_LOCK:
        _VEHICLE_INFO_CACHE = new_cache
        _LAST_REFRESH_AT = time.time()
    print(f"[VC-DEBUG] refreshed {len(result)} vehicles: {list(new_cache.keys())}")
    return result


def get_vehicle_info(vehicle_id: str) -> Optional[Dict[str, Any]]:
    """根据 vehicle_id 获取车辆信息（支持带 equipment: 前缀）"""
    vid = _normalize_vehicle_id(vehicle_id)
    with _CACHE_LOCK:
        return _VEHICLE_INFO_CACHE.get(vid)


def get_vehicle_ip(vehicle_id: str) -> Optional[str]:
    """获取车辆 IP，未找到返回 None"""
    info = get_vehicle_info(vehicle_id)
    if info:
        return info.get("ip")
    return None


def get_vehicle_vmf(vehicle_id: str) -> Optional[int]:
    """获取车辆 VMF 数字编号，未找到返回 None"""
    info = get_vehicle_info(vehicle_id)
    if not info:
        return None
    vmf_raw = info.get("VMF") or info.get("vmf")
    if vmf_raw is None:
        return None
    try:
        return int(vmf_raw)
    except (ValueError, TypeError):
        return None


def get_connected_vehicle_ids() -> List[str]:
    """获取当前已连接车辆 ID 列表"""
    with _CACHE_LOCK:
        return list(_VEHICLE_INFO_CACHE.keys())


def get_first_connected_vehicle_id() -> Optional[str]:
    """获取第一台已连接车辆 ID（列表第一个）"""
    ids = get_connected_vehicle_ids()
    return ids[0] if ids else None


def get_all_vehicle_info() -> List[Dict[str, Any]]:
    """获取缓存中所有车辆信息"""
    with _CACHE_LOCK:
        return list(_VEHICLE_INFO_CACHE.values())


def ensure_vehicle_info(
    vehicle_id: str,
    vmf: Optional[int] = None,
    ip: Optional[str] = None,
    name: Optional[str] = None,
    vehicle_type: Optional[Any] = None,
) -> Dict[str, Any]:
    """确保缓存中存在指定车辆信息（资源池兜底时注入）。返回该车辆缓存条目。"""
    vid = _normalize_vehicle_id(vehicle_id)
    with _CACHE_LOCK:
        info = _VEHICLE_INFO_CACHE.get(vid)
        if not info:
            info = {"vehicle_id": vid, "vid": vid}
            _VEHICLE_INFO_CACHE[vid] = info
        if vmf is not None:
            info["VMF"] = vmf
            info["vmf"] = vmf
        if ip is not None:
            info["ip"] = ip
        if name is not None:
            info["name"] = name
        if vehicle_type is not None:
            info["type"] = vehicle_type
        return info


_SELECTED_VEHICLE_ID: Optional[str] = None


def get_selected_vehicle_id() -> Optional[str]:
    """获取当前选中的车辆 ID"""
    return _SELECTED_VEHICLE_ID


def set_selected_vehicle_id(vehicle_id: str) -> None:
    """设置当前选中的车辆 ID"""
    global _SELECTED_VEHICLE_ID
    _SELECTED_VEHICLE_ID = _normalize_vehicle_id(vehicle_id)


def get_selected_vehicle_info() -> Optional[Dict[str, Any]]:
    """获取当前选中车辆的详细信息"""
    vid = get_selected_vehicle_id()
    if not vid:
        return None
    return get_vehicle_info(vid)


def _auto_refresh_loop(interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS):
    """后台定时刷新车辆信息（如需启用可由 lifespan 启动线程）"""
    while True:
        time.sleep(interval_seconds)
        try:
            refresh_vehicle_info()
        except Exception as e:
            print(f"[VC-DEBUG] auto refresh error: {e}")


def start_auto_refresh(interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS):
    """启动后台定时刷新线程"""
    t = threading.Thread(target=_auto_refresh_loop, args=(interval_seconds,), daemon=True)
    t.start()
    print(f"[VC-DEBUG] auto refresh started, interval={interval_seconds}s")
