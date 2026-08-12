"""统一响应包装（SP-API-GEN）：`{code, message, data, trace_id}`。"""
from __future__ import annotations

import uuid

from fastapi.responses import JSONResponse


def new_trace_id() -> str:
    return f"t_{uuid.uuid4().hex[:16]}"


def ok(data: dict, trace_id: str | None = None) -> dict:
    """成功包装（code=0）。"""
    return {"code": 0, "message": "ok", "data": data, "trace_id": trace_id or new_trace_id()}


def err(
    code: int,
    http_status: int,
    message: str,
    data: dict | None = None,
    trace_id: str | None = None,
) -> JSONResponse:
    """错误包装（错误码见 SP-API-GEN 表）；`data` 携带结构化错误信息
    （如 4220 的 rule/reason/review_required、4090 的 existing_ticket_id）。"""
    return JSONResponse(
        status_code=http_status,
        content={
            "code": code,
            "message": message,
            "data": data,
            "trace_id": trace_id or new_trace_id(),
        },
    )
