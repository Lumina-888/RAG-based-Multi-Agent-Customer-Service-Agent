"""FastAPI 入口（SP-CFG-003 骨架）。

后续模块（chat / sessions / kb / tickets / eval）在此挂载；
`/api/v1/health` 供部署探活使用（SP-DEP-001）。
注意：`setup_logging` 放 lifespan（启动时执行），不在模块导入时执行，
避免测试导入本模块产生日志副作用。
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.kb import router as kb_router
from app.api.refund import router as refund_router
from app.api.sessions import router as sessions_router
from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()  # JSON 日志在应用启动时挂载（SP-CFG-002）
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(kb_router)  # SP-ING-004 知识库管理（上传/调试检索）
app.include_router(chat_router)  # SP-CHAT-002 / SP-SSE-001 对话入口（SSE）
app.include_router(sessions_router)  # SP-CHAT-001 会话管理
app.include_router(refund_router)  # SP-REF 退款服务（建单/工单/审计）


@app.get("/api/v1/health")
async def health() -> dict:
    """健康检查：统一响应包装（SP-API-GEN：code/message/data/trace_id）。"""
    return {
        "code": 0,
        "message": "ok",
        "data": {"status": "healthy"},
        "trace_id": f"t_{uuid.uuid4().hex[:16]}",
    }
