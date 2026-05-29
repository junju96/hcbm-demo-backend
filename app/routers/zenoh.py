"""
Zenoh REST API 路由
提供状态查询、手动发布、消息拉取等接口
"""

from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import zenoh_client

router = APIRouter(prefix="/zenoh", tags=["Zenoh"])


class PublishRequest(BaseModel):
    topic: str
    payload: Any


class PublishResponse(BaseModel):
    ok: bool
    error: Optional[str] = None


@router.get("/health")
def zenoh_health():
    """查询 zenoh 会话健康状态"""
    return {
        "initialized": zenoh_client.health(),
        "error": zenoh_client.get_last_zenoh_error() or None,
    }


@router.get("/subscriptions")
def zenoh_subscriptions():
    """获取当前已订阅主题列表"""
    return {"subscriptions": zenoh_client.get_subscriptions()}


@router.post("/publish", response_model=PublishResponse)
def zenoh_publish(body: PublishRequest):
    """手动发布消息到指定 zenoh 主题"""
    ok = zenoh_client.publish(body.topic, body.payload)
    if not ok:
        return PublishResponse(ok=False, error=zenoh_client.get_last_zenoh_error())
    return PublishResponse(ok=True)


@router.get("/messages/{topic}")
def zenoh_messages(topic: str, limit: int = 50):
    """从本地缓存拉取指定主题最近消息"""
    items = zenoh_client.get_messages(topic, limit=limit)
    return {"topic": topic, "count": len(items), "messages": items}


@router.post("/subscribe-feedback/{vehicle_id}")
def zenoh_subscribe_feedback(vehicle_id: str):
    """手动订阅指定车辆的 MissionService 反馈 topic"""
    ok = zenoh_client.subscribe_vehicle_feedbacks(vehicle_id)
    return {"vehicle_id": vehicle_id, "subscribed": ok}


@router.get("/feedback")
def zenoh_feedback(topic_pattern: str = "**", limit: int = 50):
    """查询缓存的车辆反馈消息（支持通配符）"""
    items = zenoh_client.get_feedback_messages(topic_pattern, limit=limit)
    return {"topic_pattern": topic_pattern, "count": len(items), "messages": items}


@router.get("/feedback/topics")
def zenoh_feedback_topics():
    """列出当前已缓存的反馈 topic"""
    return {"topics": zenoh_client.list_feedback_topics()}
