"""SP-CHAT-002 / SP-SSE-001 对话 API：POST /api/v1/chat（SSE 事件流）。

- 入参：`{session_id, message(1~500), attachments?: [{type:"image", url}]}`
- 校验失败（缺字段/超长/附件非法）→ 4001 统一 JSON（非 SSE，无任何事件）
- 正常 → `text/event-stream`，事件序列见 SP-SSE-001；流开始后任何异常仍发送 done
- 事件持久化至 Redis，客户端带 `Last-Event-ID` 时重放断线期间事件（SP-SSE-001）
- 依赖 `ChatDeps` 可被测试 dependency_overrides 注入 Fake（CI 零外部服务）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.responses import err, new_trace_id
from app.intent.classifier import FastTextIntentClassifier, IntentClassifier
from app.memory.repo import MessageRepo, PostgresMessageRepo
from app.memory.store import RedisSessionStore, SessionStore
from app.services.chat_flow import run_chat_flow
from app.services.embedding import build_embedding_client
from app.services.es import ESClient
from app.services.llm import LLMRouter, build_llm
from app.services.refund_gateway import RefundGateway, ServiceRefundGateway

logger = logging.getLogger("app.api.chat")

router = APIRouter(prefix="/api/v1", tags=["chat"])


class Attachment(BaseModel):
    type: str
    url: str


class ChatRequest(BaseModel):
    """可选字段默认空值：Pydantic 不产生 422，统一由业务校验返回 4001。"""

    session_id: str = ""
    message: str = ""
    attachments: list[Attachment] | None = None


@dataclass
class ChatDeps:
    """对话管线依赖（测试可注入 Fake）。"""

    store: SessionStore
    repo: MessageRepo
    classifier: IntentClassifier
    llm: LLMRouter | None
    es: Any
    embedding: Any
    retrieval_top_k: int = 5
    #: 退款建单网关（SP-AGENT-003 工具依赖；M6 全量预审实现）
    refund_gateway: RefundGateway = field(default_factory=ServiceRefundGateway)


@lru_cache(maxsize=1)
def _build_deps() -> ChatDeps:
    settings = get_settings()
    try:
        classifier = FastTextIntentClassifier.load("models/intent/fasttext.bin")
    except FileNotFoundError as exc:
        raise RuntimeError(
            "意图模型未训练：请先运行 tests/integration/test_intent_model.py 或训练脚本"
        ) from exc
    return ChatDeps(
        store=RedisSessionStore(settings.redis_url),
        repo=PostgresMessageRepo(settings.postgres_dsn),
        classifier=classifier,
        llm=build_llm(settings),
        es=ESClient(settings.es_host),
        embedding=build_embedding_client(settings),
    )


def get_chat_deps() -> ChatDeps:
    """对话依赖入口：测试用 `app.dependency_overrides` 覆盖。"""
    return _build_deps()


def _validate(req: ChatRequest) -> JSONResponse | None:
    if not req.session_id.strip():
        return err(4001, 400, "session_id 不能为空（客户端生成 UUID v4）")
    if not req.message.strip():
        return err(4001, 400, "message 不能为空")
    if len(req.message) > 500:
        return err(4001, 400, f"message 长度不能超过 500 字符（当前 {len(req.message)}）")
    for att in req.attachments or []:
        if att.type != "image":
            return err(4001, 400, f"不支持的附件类型: {att.type}（仅支持 image）")
        if not att.url.strip():
            return err(4001, 400, "附件 url 不能为空")
    return None


def _format(event_name: str, data: dict, seq: int) -> str:
    """SSE 文本：`id / event / data` 三行（data 为合法 JSON）。"""
    import json

    return (
        f"id: {seq}\n"
        f"event: {event_name}\n"
        f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    )


async def _event_stream(
    deps: ChatDeps,
    session_id: str,
    message: str,
    attachments: list[dict] | None,
    user_id: str,
    last_event_id: str | None,
) -> AsyncIterator[str]:
    if last_event_id is not None:  # 断线重连：重放 id > Last-Event-ID 的事件
        for ev in await deps.store.get_events(session_id, after_id=int(last_event_id)):
            yield _format(ev["event"], ev["data"], ev["id"])
        return
    try:
        async for event_name, data, seq in run_chat_flow(
            deps, session_id, message, attachments, user_id
        ):
            yield _format(event_name, data, seq)
    except Exception as exc:  # noqa: BLE001 - 兜底：done 必须发送（SP-SSE-001）
        logger.exception("SSE 流异常 session_id=%s", session_id)
        yield _format(
            "done", {"error": {"code": 5000, "message": f"内部错误: {exc}"}}, 0
        )


@router.post("/chat")
async def chat(
    req: ChatRequest,
    request: Request,
    deps: ChatDeps = Depends(get_chat_deps),
) -> Any:
    invalid = _validate(req)
    if invalid is not None:
        logger.info("chat 参数校验失败 %s", invalid.body)
        return invalid  # 流开始前：统一 JSON（非 SSE），无任何事件

    user_id = request.headers.get("X-User-Id") or "anonymous"
    last_event_id = request.headers.get("Last-Event-ID")
    attachments = [a.model_dump() for a in req.attachments] if req.attachments else None
    trace_id = new_trace_id()
    logger.info(
        "chat 请求 session_id=%s len=%d", req.session_id, len(req.message),
        extra={"trace_id": trace_id},
    )
    return StreamingResponse(
        _event_stream(deps, req.session_id, req.message, attachments, user_id, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
