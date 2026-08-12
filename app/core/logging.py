"""统一结构化日志（SP-CFG-002）。

- 输出 JSON 格式，每条必含 `trace_id / ts / level / module`
- 敏感字段（手机号、订单号）在格式化层自动打码
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

#: 大陆手机号 11 位：保留前 3 后 4（13812345678 → 138****5678）
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
_PHONE_MASK = r"\1****\3"

#: 订单号：ORD 前缀 + 字母数字/连字符，整体打码（ORD-20260811-001 → ORD-****）
_ORDER_RE = re.compile(r"(?<![A-Za-z0-9])(ORD[-_A-Za-z0-9]{2,})(?![A-Za-z0-9])")
_ORDER_MASK = "ORD-****"


def mask_sensitive(text: str) -> str:
    """对文本中的手机号 / 订单号打码；无敏感信息时原样返回。"""
    text = _PHONE_RE.sub(_PHONE_MASK, text)
    return _ORDER_RE.sub(_ORDER_MASK, text)


class JsonFormatter(logging.Formatter):
    """JSON 行格式化器：ts/level/module/trace_id 必含，message 脱敏后输出。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "module": record.name,
            "trace_id": getattr(record, "trace_id", ""),
            "message": mask_sensitive(record.getMessage()),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _TraceAdapter(logging.LoggerAdapter):
    """带 trace_id 的 Logger 适配器（请求中间件可注入当前请求 trace_id）。"""

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        kwargs.setdefault("extra", {})["trace_id"] = self.extra["trace_id"]
        return msg, kwargs


def get_logger(name: str, trace_id: str = "") -> logging.Logger | logging.LoggerAdapter:
    """获取模块 logger；传入 trace_id 时自动附加到每条日志。"""
    logger = logging.getLogger(name)
    if trace_id:
        return _TraceAdapter(logger, {"trace_id": trace_id})
    return logger


class JsonLogHandler(logging.StreamHandler):
    """JSON 日志 Handler（统一出口；setup_logging 幂等性以其类型判定）。"""

    def __init__(self, stream: Any = None) -> None:
        super().__init__(stream)
        self.setFormatter(JsonFormatter())


def setup_logging(
    level: int = logging.INFO, handler: logging.Handler | None = None
) -> logging.Handler:
    """配置根 logger 输出 JSON（幂等：已挂 JsonLogHandler 时不重复添加）。

    注：幂等性按 `JsonLogHandler` 类型判定，避免与 pytest 等三方
    框架挂载的 StreamHandler 子类（如 _FileHandler）混淆。
    """
    handler = handler or JsonLogHandler()
    if not isinstance(handler, JsonLogHandler):
        handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, JsonLogHandler) for h in root.handlers):
        root.addHandler(handler)
    return handler
