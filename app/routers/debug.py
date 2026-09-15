"""
调试接口：后端服务地址查看/覆盖、进程原地重启

- GET  /config  当前生效的后端服务地址表（含默认值/生效值/是否被覆盖/是否需重启）
- POST /config  覆盖服务地址（写 runtime_config.json；ZENOH_ROUTER_URL 例外，
                定点改写 zenoh_py/zenoh.json5 的 connect.endpoints，需重启生效）
- POST /restart 先返回 200，0.5s 后 os.execv 原地重启后端进程
"""

import os
import re
import sys
import threading
from typing import Any, Dict

from fastapi import APIRouter, Body, HTTPException, Response

from app import config as app_config
from app.log_setup import beijing_now

router = APIRouter(prefix="/debug", tags=["调试"])

# zenoh 实际生效配置（JSON5，带注释；zenoh_py/zenoh_service.py 启动时加载）
ZENOH_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "zenoh_py", "zenoh.json5",
)

# 修改后需重启后端才生效的键：
# HTTP 地址与 SEAT_TARGET_IPS 均已 getter 化，每次请求读生效值，无需重启；
# Zenoh 会话在启动时按 zenoh.json5 建立，改地址必须重启。
RESTART_REQUIRED_KEYS = ["ZENOH_ROUTER_URL"]

_ZENOH_ENDPOINT_RE = re.compile(
    r'(connect\s*:\s*\{[^}]*?endpoints\s*:\s*\[\s*")([^"]+)(")',
    re.S,
)


def _read_zenoh_router_endpoint() -> str:
    """从 zenoh.json5 的 connect.endpoints 读取实际生效的 router 地址"""
    try:
        with open(ZENOH_CONFIG_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    m = _ZENOH_ENDPOINT_RE.search(text)
    return m.group(2) if m else ""


def _write_zenoh_router_endpoint(endpoint: str) -> None:
    """定点替换 zenoh.json5 中 connect.endpoints 的地址串，保留注释与其他内容"""
    try:
        with open(ZENOH_CONFIG_PATH, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise ValueError(f"ZENOH_ROUTER_URL: 无法读取 zenoh.json5: {e}")
    new_text, n = _ZENOH_ENDPOINT_RE.subn(
        lambda m: m.group(1) + endpoint + m.group(3), text, count=1
    )
    if n == 0:
        raise ValueError("ZENOH_ROUTER_URL: zenoh.json5 中未找到 connect.endpoints 配置")
    with open(ZENOH_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(new_text)


def _zenoh_config_item() -> Dict[str, Any]:
    default = app_config.ZENOH_ROUTER_URL
    effective = _read_zenoh_router_endpoint() or default
    return {
        "key": "ZENOH_ROUTER_URL",
        "label": "Zenoh 路由器地址",
        "default": default,
        "effective": effective,
        "overridden": effective != default,
    }


@router.get("/config")
def get_debug_config():
    """返回当前生效的后端服务地址表"""
    items = app_config.get_effective_config()
    items.append(_zenoh_config_item())
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "items": items,
            "restart_required": list(RESTART_REQUIRED_KEYS),
        },
    }


@router.post("/config")
def update_debug_config(patch: Dict[str, Any] = Body(...)):
    """覆盖服务地址。body 为 {key: value} 补丁（也兼容 {"overrides": {key: value}} 包装）；
    值为空字符串表示恢复默认。校验失败返回 400 + 字段错误"""
    patch = dict(patch or {})
    # 兼容前端 {"overrides": {...}} 包装
    if set(patch.keys()) == {"overrides"} and isinstance(patch["overrides"], dict):
        patch = dict(patch["overrides"])
    zenoh_url = patch.pop("ZENOH_ROUTER_URL", None)

    try:
        overrides = (
            app_config.update_runtime_overrides(patch)
            if patch
            else app_config.get_runtime_overrides()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    restart_required = []
    if zenoh_url is not None:
        if zenoh_url == "":
            # 空串 = 恢复默认：把 zenoh.json5 改回 config.py 里的默认地址
            zenoh_url = app_config.ZENOH_ROUTER_URL
        if not isinstance(zenoh_url, str) or not zenoh_url.startswith("tcp/"):
            raise HTTPException(
                status_code=400,
                detail="ZENOH_ROUTER_URL: 必须是以 tcp/ 开头的 zenoh 端点（如 tcp/25.11.1.3:7447）",
            )
        try:
            _write_zenoh_router_endpoint(zenoh_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        restart_required.append("ZENOH_ROUTER_URL")

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "overrides": overrides,
            "restart_required": restart_required,
        },
    }


def _restart_process():
    # python -m uvicorn 启动时 sys.argv[0] 是包内 __main__.py 的路径
    # （如 .../uvicorn/__main__.py），execv 该路径可行但不规范，还原为 -m 形式；
    # PyInstaller 打包二进制下 sys.executable 即二进制本身、sys.argv[0] 为二进制路径，
    # 原样 execv 即可，两种形态都兼容。
    argv = list(sys.argv)
    if argv and os.path.basename(argv[0]) == "__main__.py":
        pkg = os.path.basename(os.path.dirname(argv[0]))
        argv = ["-m", pkg] + argv[1:]
    os.execv(sys.executable, [sys.executable] + argv)


@router.post("/restart")
def restart_backend():
    """立即返回 200，0.5s 后 os.execv 原地重启后端进程。

    机制：execv 用同一命令行替换当前进程镜像（PID 不变），不依赖外部守护；
    对 `python -m uvicorn ...` 与 PyInstaller 二进制启动方式均适用。
    限制：若进程由 systemd/守护脚本管理且启动命令与本进程 argv 不一致，
    拉起的是本进程自身命令行而非守护配置；进程退出码对 execv 透明。
    """
    threading.Timer(0.5, _restart_process).start()
    return {"code": 200, "message": "restarting"}


# ---------- 后端日志导出 ----------

# 主运行日志路径：app_ctl.sh 开发环境为 backend-dev/backend-28600-run.log；
# 现场二进制部署可用环境变量 BACKEND_LOG_FILE 指向实际日志文件。
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_LOG_FILE = os.environ.get(
    "BACKEND_LOG_FILE", os.path.join(_BACKEND_ROOT, "backend-28600-run.log")
)

# 只允许导出这两个已知日志文件，不接受任意路径（防目录穿越）
_LOG_SOURCES = {
    "backend": ("backend", lambda: BACKEND_LOG_FILE),
    "zenoh": ("zenoh-payload", lambda: os.environ.get("ZENOH_LOG_FILE", "/tmp/zenoh_payload.log")),
}


@router.get("/logs")
def export_backend_logs(source: str = "backend"):
    """下载后端日志文件（text/plain，Content-Disposition 带文件名）。

    source=backend：主运行日志；source=zenoh：zenoh 接口日志（ZENOH_LOG_FILE）。

    注意：日志文件在持续写入，不能用 FileResponse——它按 stat 时的 size 填
    Content-Length，文件随后增长会导致发送字节数与声明不符、keep-alive 连接挂起
    （经 vite 代理实测下载卡死）。这里改为一次性读入内存返回，超过 10MB 只取尾部
    并在开头标注截断。
    """
    entry = _LOG_SOURCES.get(source)
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail=f"source: 不支持的日志源（可选: {', '.join(_LOG_SOURCES)}）",
        )
    name, get_path = entry
    path = get_path()
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"日志文件不存在: {path}")

    max_bytes = 10 * 1024 * 1024
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            data = f.read()
            # 丢弃可能截断的半行，并标注截断点
            data = data.split(b"\n", 1)[-1]
            marker = f"[截断] 日志共 {size} 字节，仅导出末尾 {max_bytes} 字节\n".encode("utf-8")
            data = marker + data
        else:
            data = f.read()

    stamp = beijing_now().replace("-", "").replace(" ", "-").replace(":", "").split(".")[0]
    return Response(
        content=data,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.log"'},
    )
