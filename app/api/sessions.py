"""SP-CHAT-001 会话管理 API：历史查询（归属校验 4030）/ 删除清空。

- `GET /api/v1/sessions/{sid}/messages`：时间升序消息列表，含 intent / conf /
  agent_route；未认证 4010（SP-SEC-003）；会话归属校验 4030（不泄露数据）
- `DELETE /api/v1/sessions/{sid}`：清空会话（消息历史 + 短期上下文 + 事件序列）
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.auth import get_current_user
from app.api.chat import ChatDeps, get_chat_deps
from app.core.responses import err, ok

logger = logging.getLogger("app.api.sessions")

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


async def _ownership(
    session_id: str, deps: ChatDeps, user_id: str | None
) -> JSONResponse | None:
    """会话归属校验（SP-CHAT-001）：未认证 4010；不存在 4040；他人 4030。"""
    if user_id is None:
        return err(4010, 401, "未登录或会话无效")
    owner = await deps.repo.get_session_owner(session_id)
    if owner is None:
        return err(4040, 404, "会话不存在")
    if owner != user_id:
        return err(4030, 403, "无权访问该会话")
    return None


@router.get("/{session_id}/messages")
async def list_messages(
    session_id: str,
    deps: ChatDeps = Depends(get_chat_deps),
    user_id: str | None = Depends(get_current_user),
) -> dict:
    denied = await _ownership(session_id, deps, user_id)
    if denied is not None:
        return denied
    messages = await deps.repo.list_messages(session_id)
    return ok({"session_id": session_id, "count": len(messages),
               "messages": [m.as_dict() for m in messages]})


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    deps: ChatDeps = Depends(get_chat_deps),
    user_id: str | None = Depends(get_current_user),
) -> dict:
    denied = await _ownership(session_id, deps, user_id)
    if denied is not None:
        return denied
    await deps.repo.delete_session(session_id)  # 消息历史清空（PG）
    await deps.store.clear(session_id)  # 短期上下文 + 事件序列清空（Redis）
    logger.info("会话已清空 session_id=%s", session_id)
    return ok({"session_id": session_id, "deleted": True})
