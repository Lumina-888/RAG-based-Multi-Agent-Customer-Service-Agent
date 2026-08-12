"""FastAPI 入口（SP-CFG-003 骨架）。

后续模块（chat / sessions / kb / tickets / eval）在此挂载；
`/api/v1/health` 供部署探活使用（SP-DEP-001）。
注意：`setup_logging` 放 lifespan（启动时执行），不在模块导入时执行，
避免测试导入本模块产生日志副作用。
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.eval import router as eval_router
from app.api.kb import router as kb_router
from app.api.refund import router as refund_router
from app.api.sessions import router as sessions_router
from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()

#: 前端构建产物目录（SP-DEP-001：Docker 多阶段构建把 dist 打进 app/static；
#: 本地未构建时该目录不存在 → SPA 回退返回 404，不影响 API）
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging()  # JSON 日志在应用启动时挂载（SP-CFG-002）
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(kb_router)  # SP-ING-004 知识库管理（上传/调试检索）
app.include_router(auth_router)  # SP-SEC-003 认证（登录/token）
app.include_router(chat_router)  # SP-CHAT-002 / SP-SSE-001 对话入口（SSE）
app.include_router(sessions_router)  # SP-CHAT-001 会话管理
app.include_router(refund_router)  # SP-REF 退款服务（建单/工单/审计）
app.include_router(eval_router)  # SP-EVAL 评测（看板数据源 GET /eval/runs）


@app.get("/api/v1/health")
async def health() -> dict:
    """健康检查：统一响应包装（SP-API-GEN：code/message/data/trace_id）。"""
    return {
        "code": 0,
        "message": "ok",
        "data": {"status": "healthy"},
        "trace_id": f"t_{uuid.uuid4().hex[:16]}",
    }


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    """前端静态资源（SP-DEP-001）：dist 由 FastAPI 托管，SPA 路由回退 index.html。

    - 命中真实文件（js/css/图片等）→ FileResponse
    - 其余路径（SPA 路由如 /eval、/tickets）→ index.html
    - 未构建前端（STATIC_DIR 不存在）→ 404 JSON，不影响 API
    """
    if STATIC_DIR.is_dir():
        if full_path:
            target = STATIC_DIR / full_path
            if target.is_file():
                return FileResponse(target)
        index = STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
    return JSONResponse({"detail": "Not Found"}, status_code=404)
