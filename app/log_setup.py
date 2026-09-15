"""
日志时间戳统一为北京时间（UTC+8）。

- 包装 sys.stdout / sys.stderr：给每个完整行加 "[YYYY-MM-DD HH:mm:ss.SSS] " 前缀
  （已自带时间戳的行——如 [TM] / zenoh 日志——不重复加）；
- uvicorn 的 logging handler 换成带北京时间的 formatter（覆盖 uvicorn 自身 INFO 行）。

用法：app/main.py 顶部 `from app.log_setup import install; install()`；幂等，重复调用不叠加。
现场席位机时区设置不可控，因此用固定 UTC+8 偏移，不依赖设备时区。
"""

import logging
import re
import sys
from datetime import datetime, timedelta, timezone

_BEIJING_TZ = timezone(timedelta(hours=8), name="UTC+8")
_TS_PREFIX_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
_installed = False


def beijing_now() -> str:
    """当前北京时间，格式 YYYY-MM-DD HH:mm:ss.SSS"""
    return datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


class _TimestampedStream:
    """行级流包装：每行输出前补北京时间戳；不带换行的片段先缓存，flush 时补齐。"""

    def __init__(self, stream):
        self._stream = stream
        self._pending = ""

    def write(self, data):
        if not data:
            return 0
        text = data if isinstance(data, str) else str(data)
        self._pending += text
        lines = self._pending.split("\n")
        self._pending = lines.pop()  # 最后一段可能是不完整行，先缓存
        for line in lines:
            self._write_line(line)
        return len(data)

    def _write_line(self, line):
        if line and not _TS_PREFIX_RE.match(line):
            line = f"[{beijing_now()}] {line}"
        self._stream.write(line + "\n")

    def flush(self):
        if self._pending:
            self._write_line(self._pending)
            self._pending = ""
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _beijing_format_time(record, datefmt=None):
    """logging.Formatter.formatTime 的实例级替换：asctime 按北京时间渲染。"""
    dt = datetime.fromtimestamp(record.created, _BEIJING_TZ)
    return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def _patch_logger(logger_name: str) -> None:
    """给已存在 handler 的 formatter 前加 [asctime]（北京时间）。

    不替换 formatter 类——uvicorn 的 AccessFormatter 等在 format() 里注入
    %(levelprefix)s/%(client_addr)s 等私有字段，换类会 KeyError。改为实例级
    补丁：_fmt（含 _style._fmt）前加 asctime 前缀 + 替换实例的 formatTime。
    """
    logger = logging.getLogger(logger_name)
    for handler in logger.handlers:
        fmt = handler.formatter
        if fmt is None:
            fmt = logging.Formatter("%(levelname)s %(message)s")
            handler.setFormatter(fmt)
        base = getattr(fmt, "_fmt", None) or "%(message)s"
        if "%(asctime)s" in base:
            continue  # 幂等：已加过时间前缀则跳过
        new_fmt = f"[%(asctime)s] {base}"
        fmt._fmt = new_fmt
        style = getattr(fmt, "_style", None)
        if style is not None:
            style._fmt = new_fmt
        fmt.formatTime = _beijing_format_time


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    if not isinstance(sys.stdout, _TimestampedStream):
        sys.stdout = _TimestampedStream(sys.stdout)
    if not isinstance(sys.stderr, _TimestampedStream):
        sys.stderr = _TimestampedStream(sys.stderr)
    # uvicorn 的 logging handler 在 Config 构造时创建，早于 app import，此处可直接补丁；
    # 早于本模块加载的极个别启动行可能仍无时间戳，属可接受范围。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _patch_logger(name)
