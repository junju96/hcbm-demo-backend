"""
Zenoh 客户端封装层
为 FastAPI 后端提供发布/订阅能力，桥接 zenoh_py/zenoh_service
"""

import json
import threading
from typing import Any, Callable, Dict, List, Optional

from zenoh_py.zenoh_service import (
    close_zenoh,
    get_last_error,
    health as _zenoh_health,
    initialize as _zenoh_initialize,
    list_subscriptions,
    poll_topic,
    publish_topic,
    subscribe_topic,
    _DEFAULT_CLIENT,
)

# ---------- 状态 ----------
_initialized: bool = False
_init_lock = threading.Lock()
_message_callbacks: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
_default_topics: List[str] = []
_feedback_buffers: Dict[str, List[Dict[str, Any]]] = {}
_feedback_buffer_lock = threading.Lock()
FEEDBACK_BUFFER_SIZE = 200


def initialize(
    auto_subscribe_defaults: bool = True,
    topics: Optional[List[str]] = None,
    on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> bool:
    """启动时初始化 zenoh 会话"""
    global _initialized, _default_topics

    with _init_lock:
        if _initialized:
            return True

        print("[Zenoh] Initializing...")
        ok = _zenoh_initialize(auto_subscribe_defaults=auto_subscribe_defaults)
        if not ok:
            print(f"[Zenoh] initialize failed: {get_last_error()}")
            return False

        _initialized = True

        # 检测当前是 router 模式还是 local-peer 回退模式
        is_local = getattr(_DEFAULT_CLIENT, "_local_peer_active", False)
        config_path = getattr(_DEFAULT_CLIENT, "_default_config_path", None)
        if is_local:
            print("[Zenoh] Session initialized (LOCAL-PEER FALLBACK MODE — no external router)")
        else:
            print("[Zenoh] Session initialized (ROUTER MODE)")
        print(f"[Zenoh] Config path: {config_path}")

        # 订阅用户指定的主题
        if topics:
            for topic in topics:
                subscribe(topic=topic, on_message=on_message)
                _default_topics.append(topic)

        return True


def close() -> bool:
    """关闭 zenoh 会话"""
    global _initialized, _message_callbacks, _default_topics

    with _init_lock:
        if not _initialized:
            return True

        ok = close_zenoh()
        _initialized = False
        _message_callbacks.clear()
        _default_topics.clear()

        if ok:
            print("[Zenoh] Session closed.")
        else:
            print(f"[Zenoh] close failed: {get_last_error()}")
        return ok


def health() -> bool:
    """检查 zenoh 会话是否健康"""
    if not _initialized:
        return False
    return _zenoh_health()


def publish(topic: str, payload: Any) -> bool:
    """发布消息到指定主题"""
    if not _initialized:
        print("[Zenoh] cannot publish: not initialized")
        return False

    # 判断当前模式
    is_local = getattr(_DEFAULT_CLIENT, "_local_peer_active", False)
    mode = "LOCAL-PEER" if is_local else "ROUTER"

    payload_str = json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    print(f"[ZENOH-OUT] mode={mode} | topic={topic} | payload_size={len(payload_str.encode('utf-8'))} bytes")

    ok = publish_topic(topic, payload)
    if not ok:
        print(f"[Zenoh] publish to '{topic}' failed: {get_last_error()}")
    else:
        print(f"[ZENOH-OUT] publish ok | topic={topic} | mode={mode}")
    return ok


def _dispatch_message(message: Dict[str, Any]) -> None:
    """内部消息分发：按主题匹配，调用所有注册回调"""
    topic = message.get("topic", "")
    for subscribed_topic, callbacks in list(_message_callbacks.items()):
        if _topic_matches(subscribed_topic, topic):
            for cb in callbacks:
                try:
                    cb(message)
                except Exception as exc:
                    print(f"[Zenoh] callback error on '{subscribed_topic}': {exc}")


def subscribe(
    topic: str,
    buffer_size: Optional[int] = None,
    on_message: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> bool:
    """订阅主题，可注册回调"""
    if not _initialized:
        print("[Zenoh] cannot subscribe: not initialized")
        return False

    # 注册回调
    if on_message is not None:
        if topic not in _message_callbacks:
            _message_callbacks[topic] = []
        _message_callbacks[topic].append(on_message)

    # 首次订阅该 topic 时，才调底层 subscribe_topic
    # 复用内部 _dispatch_message 作为统一入口
    ok = subscribe_topic(
        topic=topic,
        buffer_size=buffer_size,
        on_message=_dispatch_message,
    )
    if not ok:
        print(f"[Zenoh] subscribe '{topic}' failed: {get_last_error()}")
    else:
        print(f"[Zenoh] subscribed: {topic}")
    return ok


def get_subscriptions() -> List[str]:
    """获取当前已订阅主题列表"""
    return list_subscriptions()


def get_messages(topic: str, limit: int = 50) -> List[Dict[str, Any]]:
    """从本地缓存拉取指定主题最近消息"""
    return poll_topic(topic, limit=limit)


def _topic_matches(pattern: str, topic: str) -> bool:
    """简单的主题通配符匹配：支持 * 和 **"""
    import re

    if pattern == topic:
        return True
    escaped = re.escape(pattern)
    escaped = escaped.replace(r"\*\*", "__ZENOH_MULTI__")
    escaped = escaped.replace(r"\*", "[^/]*")
    escaped = escaped.replace("__ZENOH_MULTI__", ".*")
    return re.fullmatch(escaped, topic) is not None


def get_last_zenoh_error() -> str:
    """获取最近一次 zenoh 错误"""
    return get_last_error()


def subscribe_vehicle_feedbacks(vehicle_id: str) -> bool:
    """
    订阅指定车辆的所有 MissionService 反馈 topic。
    根据协议文档订阅：ack、task_received_status、mission_status、navi/data、chassis_resource
    """
    if not _initialized:
        print(f"[Zenoh] cannot subscribe feedbacks: not initialized")
        return False

    topics = [
        f"mgmt/t01/g01/v{vehicle_id}/cmd/ack",
        f"op/t01/g01/v{vehicle_id}/mission/task_received_status",
        f"op/t01/g01/v{vehicle_id}/mission/mission_status",
        f"op/t01/g01/v{vehicle_id}/resource/chassis_resource",
    ]

    ok_all = True
    for topic in topics:
        ok = subscribe_topic(topic=topic, buffer_size=FEEDBACK_BUFFER_SIZE, on_message=_on_feedback_message)
        if ok:
            print(f"[Zenoh] feedback subscribed: {topic}")
        else:
            print(f"[Zenoh] feedback subscribe failed: {topic} | err={get_last_error()}")
            ok_all = False
    return ok_all


def _on_feedback_message(message: Dict[str, Any]) -> None:
    """车辆反馈消息回调：打印日志 + 缓存"""
    topic = message.get("topic", "")
    payload_text = message.get("payload_text", "")
    timestamp = message.get("timestamp", "")

    # 打印入站日志
    print(f"[ZENOH-IN] topic={topic} | ts={timestamp} | payload={payload_text[:800]}")

    # 缓存
    with _feedback_buffer_lock:
        if topic not in _feedback_buffers:
            _feedback_buffers[topic] = []
        _feedback_buffers[topic].append(message)
        # 只保留最近 N 条
        if len(_feedback_buffers[topic]) > FEEDBACK_BUFFER_SIZE:
            _feedback_buffers[topic] = _feedback_buffers[topic][-FEEDBACK_BUFFER_SIZE:]


def get_feedback_messages(topic_pattern: str, limit: int = 50) -> List[Dict[str, Any]]:
    """按 topic 通配符查询缓存的反馈消息"""
    import re

    results: List[Dict[str, Any]] = []
    with _feedback_buffer_lock:
        for topic, items in _feedback_buffers.items():
            if _topic_matches(topic_pattern, topic):
                results.extend(items)
    # 按时间戳倒序，取最近 limit 条
    results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return results[:limit]


def list_feedback_topics() -> List[str]:
    """列出当前有缓存数据的反馈 topic"""
    with _feedback_buffer_lock:
        return list(_feedback_buffers.keys())
