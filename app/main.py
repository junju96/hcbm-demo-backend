"""
ZK 软件指控后端服务 — FastAPI
提供杀伤链(Kill Chain)管理、SSE双流、task_pool代理等接口
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time
import json

from app.routers import kill_chain, planning, action_sequence, ssl, zenoh as zenoh_router
from app.services.task_pool import task_pool
from app.services.sse_manager import sse_manager
from app.services import zenoh_client
from app.data.mock_data import preload_mock_data
from app.services import vehicle_control_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时预置 mock 数据
    preload_mock_data(task_pool)
    app.state.task_pool = task_pool
    app.state.sse_manager = sse_manager

    # 初始化车辆控制服务车辆信息缓存
    vehicle_control_client.refresh_vehicle_info()
    vehicle_control_client.start_auto_refresh()

    # 初始化 zenoh（local_peer_fallback 允许无 router 时本地回退）
    zenoh_ok = zenoh_client.initialize(auto_subscribe_defaults=True)
    if zenoh_ok:
        print("[ZK Backend] Zenoh ready. Vehicle feedback subscription is deferred until user selects a vehicle.")
    else:
        print(f"[ZK Backend] Zenoh init failed (may fall back to local-peer): {zenoh_client.get_last_zenoh_error()}")

    print("[ZK Backend] Mock data loaded. Ready.")
    yield
    # 关闭时清理
    sse_manager.close_all()
    zenoh_client.close()
    print("[ZK Backend] Shutting down.")


class RequestLogMiddleware:
    """请求/响应日志中间件 — 通过拦截 send 捕获完整的请求体和响应体"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        method = request.method
        path = request.url.path
        client = scope.get("client", ("unknown", 0))

        # 跳过静态资源、SSE 流
        skip_detail = (
            path in ("/docs", "/redoc", "/openapi.json")
            or path.startswith("/api/v1/planning/events")
        )

        # 轮询接口日志开关：设置 SKIP_POLL_LOG=1 可跳过列表/详情查询日志，避免刷屏
        if os.environ.get("SKIP_POLL_LOG"):
            import re
            skip_detail = skip_detail or bool(re.match(
                r"^/api/v1/action-sequences/(operator/)?plans(/[^/]+)?$",
                path,
            ))

        # 读取请求体（可重复读取）
        req_body = ""
        if method in ("POST", "PUT", "PATCH") and not skip_detail:
            body_bytes = await request.body()
            async def receive_with_body():
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            request = Request(scope, receive_with_body)
            req_body = body_bytes.decode("utf-8", errors="ignore") if body_bytes else ""

        # 收集响应
        resp_status = 200
        resp_headers = []
        resp_chunks = []

        async def logging_send(message):
            nonlocal resp_status
            if message["type"] == "http.response.start":
                resp_status = message.get("status", 200)
                resp_headers = message.get("headers", [])
                await send(message)
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    resp_chunks.append(chunk)
                await send(message)

        start = time.time()
        await self.app(scope, request.receive, logging_send)
        cost_ms = (time.time() - start) * 1000

        # 格式化并打印
        if not skip_detail:
            client_addr = f"{client[0]}:{client[1]}"

            # 格式化请求体
            req_pretty = ""
            if req_body:
                try:
                    req_pretty = json.dumps(json.loads(req_body), ensure_ascii=False, indent=2)
                except Exception:
                    req_pretty = req_body[:500]

            # 格式化响应体
            resp_body = b"".join(resp_chunks).decode("utf-8", errors="ignore")
            resp_pretty = ""
            if resp_body:
                try:
                    resp_pretty = json.dumps(json.loads(resp_body), ensure_ascii=False, indent=2)
                except Exception:
                    resp_pretty = resp_body[:500]

            # 打印分隔线，易读格式
            sep = "─" * 60
            print(f"\n{sep}")
            print(f"[→ IN ] {method} {path} | client={client_addr} | status={resp_status} | time={cost_ms:.2f}ms")
            if req_pretty:
                print(f"[Request Body]\n{req_pretty}")
            if resp_pretty:
                print(f"[Response Body]\n{resp_pretty}")
            print(f"{sep}\n")


app = FastAPI(
    title="ZK 指控后端服务",
    description="杀伤链管理 / 方案规划 / SSE 事件流",
    version="0.1.0",
    lifespan=lifespan,
)

# 请求/响应日志 — 联调时查看每个接口的入参和出参
# 如需只打印 zenoh 调试日志，设置环境变量 ZENOH_ONLY_LOG=1
import os
if not os.environ.get("ZENOH_ONLY_LOG"):
    app.add_middleware(RequestLogMiddleware)

# CORS — 允许前端跨域调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(kill_chain.router, prefix="/api/v1", tags=["杀伤链"])
app.include_router(planning.router, prefix="/api/v1", tags=["规划事件流"])
app.include_router(action_sequence.router, prefix="/api/v1", tags=["行动序列"])
app.include_router(ssl.router, prefix="/api/v1", tags=["SSL地图数据"])
app.include_router(zenoh_router.router, prefix="/api/v1", tags=["Zenoh"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "zk-backend"}


# 本地启动入口
if __name__ == "__main__":
    import uvicorn
    import os
    PORT = int(os.environ.get("ZK_BACKEND_PORT", "28600"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=True)
