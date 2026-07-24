"""
SSE 事件流管理服务
管理 overview + detail 双流
"""

import asyncio
import json
from typing import Dict, List, Any, AsyncGenerator
from datetime import datetime, timezone


class SSEManager:
    """SSE 连接与事件推送管理"""

    def __init__(self):
        # overview: scope -> [queue]
        self._overview_queues: Dict[str, List[asyncio.Queue]] = {}
        # detail: "resource_type:resource_id" -> [queue]
        self._detail_queues: Dict[str, List[asyncio.Queue]] = {}

    # ---------- 注册 / 注销 ----------

    def register_overview(self, scope: str) -> asyncio.Queue:
        q = asyncio.Queue()
        if scope not in self._overview_queues:
            self._overview_queues[scope] = []
        self._overview_queues[scope].append(q)
        return q

    def unregister_overview(self, scope: str, q: asyncio.Queue) -> None:
        if scope in self._overview_queues:
            if q in self._overview_queues[scope]:
                self._overview_queues[scope].remove(q)

    def register_detail(self, resource_type: str, resource_id: str) -> asyncio.Queue:
        key = f"{resource_type}:{resource_id}"
        q = asyncio.Queue()
        if key not in self._detail_queues:
            self._detail_queues[key] = []
        self._detail_queues[key].append(q)
        return q

    def unregister_detail(self, resource_type: str, resource_id: str, q: asyncio.Queue) -> None:
        key = f"{resource_type}:{resource_id}"
        if key in self._detail_queues:
            if q in self._detail_queues[key]:
                self._detail_queues[key].remove(q)

    # ---------- 推送事件 ----------

    async def push_overview(self, scope: str, event: str, data: Dict[str, Any]) -> None:
        queues = self._overview_queues.get(scope, [])
        msg = {"event": event, "data": data}
        for q in list(queues):
            try:
                await q.put(msg)
            except Exception:
                pass

    async def push_detail(self, resource_type: str, resource_id: str, event: str, data: Dict[str, Any]) -> None:
        key = f"{resource_type}:{resource_id}"
        queues = self._detail_queues.get(key, [])
        msg = {"event": event, "data": data}
        for q in list(queues):
            try:
                await q.put(msg)
            except Exception:
                pass

    # ---------- 便捷方法 ----------

    async def push_kill_chain_detail(self, resource_id: str, event: str, detail: Dict[str, Any], message: str = "") -> None:
        data = {
            "resource_type": "kill_chain",
            "resource_id": resource_id,
            "action": event.split(".")[-1].upper(),
            "message": message,
            "detail": detail,
        }
        await self.push_detail("kill_chain", resource_id, event, data)

    async def push_overview_changed(self, scope: str, resource_type: str, resource_id: str, summary: Dict[str, Any], action: str = "PATCH") -> None:
        data = {
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
            "summary": summary,
        }
        await self.push_overview(scope, "planning.overview.changed", data)

    # ---------- 生成 SSE 流 ----------

    async def event_generator(self, q: asyncio.Queue, keepalive_interval: float = 30.0) -> AsyncGenerator[str, None]:
        """从队列生成 SSE 格式字符串流"""
        last_activity = datetime.now(timezone.utc).timestamp()
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=keepalive_interval)
                event = msg.get("event", "message")
                data = msg.get("data", {})
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                last_activity = datetime.now(timezone.utc).timestamp()
            except asyncio.TimeoutError:
                # 发送心跳
                now = datetime.now(timezone.utc).isoformat()
                yield f"event: system.heartbeat\ndata: {json.dumps({'timestamp': now}, ensure_ascii=False)}\n\n"
            except Exception as e:
                print(f"[SSE] event_generator error: {e}")
                break

    # ---------- 清理 ----------

    def close_all(self) -> None:
        for queues in self._overview_queues.values():
            for q in queues:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass
        for queues in self._detail_queues.values():
            for q in queues:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass


# 全局单例
sse_manager = SSEManager()
