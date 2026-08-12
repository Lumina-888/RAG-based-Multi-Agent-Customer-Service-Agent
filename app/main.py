"""FastAPI 入口（SP-CFG-003 骨架）。

后续模块（chat / sessions / kb / tickets / eval）在此挂载；
`/api/v1/health` 供部署探活使用（SP-DEP-001）。
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()
setup_logging()

app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/api/v1/health")
async def health() -> dict:
    """健康检查：统一响应包装（SP-API-GEN：code/message/data/trace_id）。"""
    return {
        "code": 0,
        "message": "ok",
        "data": {"status": "healthy"},
        "trace_id": f"t_{uuid.uuid4().hex[:16]}",
    }
