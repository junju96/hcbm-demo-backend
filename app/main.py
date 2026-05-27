"""
ZK 软件指控后端服务 — FastAPI
提供杀伤链(Kill Chain)管理、SSE双流、task_pool代理等接口
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.routers import kill_chain, planning
from app.services.task_pool import task_pool
from app.services.sse_manager import sse_manager
from app.data.mock_data import preload_mock_data


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时预置 mock 数据
    preload_mock_data(task_pool)
    app.state.task_pool = task_pool
    app.state.sse_manager = sse_manager
    print("[ZK Backend] Mock data loaded. Ready.")
    yield
    # 关闭时清理
    sse_manager.close_all()
    print("[ZK Backend] Shutting down.")


app = FastAPI(
    title="ZK 指控后端服务",
    description="杀伤链管理 / 方案规划 / SSE 事件流",
    version="0.1.0",
    lifespan=lifespan,
)

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


@app.get("/health")
def health():
    return {"status": "ok", "service": "zk-backend"}


# 本地启动入口
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=28600, reload=True)
