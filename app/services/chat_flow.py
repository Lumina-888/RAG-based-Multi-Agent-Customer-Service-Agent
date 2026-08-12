"""对话编排（SP-CHAT / SP-SSE）：由 M5 LangGraph 状态机（SP-AGENT-004）驱动。

本层职责（M4 的编排内联逻辑已迁入 `app/agents/graph.py`）：
- 初始状态构造：会话上下文注入 + CONFIRM 挂起上下文（Redis）读取
- 图执行：`graph.ainvoke` → 消费节点产出的 `_sse` 事件（顺序由节点保证）
- SSE 事件持久化（session:{id}:events，Last-Event-ID 重放）与 done 兜底
- 挂起/转人工状态落库（Redis），消息历史落库（PG）

事件协议（SP-SSE-001）与 M4 一致：
intent → route → (vision) → (retrieval/tool_call) → message(delta) → done；
澄清/转人工路径无 retrieval；错误路径 done 带 error。
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from app.agents.graph import execute_graph
from app.services.llm import LLMUnavailableError

logger = logging.getLogger("app.services.chat_flow")


def _error_data(error_code: int | None, exc: Exception | None = None) -> dict:
    if error_code == 5001:
        return {"code": 5001, "message": "LLM 服务不可用，请稍后重试"}
    if exc is not None:
        return {"code": 5000, "message": f"内部错误: {exc}"}
    return {"code": 5000, "message": "内部错误"}


async def _emit(deps: Any, session_id: str, event: str, data: dict) -> int:
    """事件持久化至 session:{id}:events，返回序号（SSE id / Last-Event-ID）。"""
    return await deps.store.append_event(session_id, {"event": event, "data": data})


async def run_chat_flow(
    deps: Any,
    session_id: str,
    message: str,
    attachments: list[dict] | None = None,
    user_id: str = "anonymous",
) -> AsyncIterator[tuple[str, dict, int]]:
    """一次对话请求的完整事件流：`(event, data, seq)`，保证以 done 结尾。"""
    store, repo = deps.store, deps.repo
    await repo.ensure_session(session_id, user_id)
    await repo.add_message(session_id, "user", message)

    # CONFIRM 挂起上下文（SP-AGENT-004）：跨请求读取待确认的建单参数
    pending = await store.get_pending_confirm(session_id)
    try:
        state = await execute_graph(
            deps,
            session_id=session_id,
            user_id=user_id,
            message=message,
            attachments=attachments,
            pending=pending,
        )
    except Exception as exc:  # noqa: BLE001 - 图级兜底：done 必须发送
        logger.exception("对话编排异常 session_id=%s", session_id)
        await _emit(deps, session_id, "done", {"error": _error_data(None, exc)})
        yield ("done", {"error": _error_data(None, exc)}, 0)
        return

    # 节点事件按序透出（intent/route/vision/retrieval/tool_call/message）
    for item in state.get("_sse", []):
        seq = await _emit(deps, session_id, item["event"], item["data"])
        yield (item["event"], item["data"], seq)

    # 挂起/取消后清理 pending；转人工摘要由 transfer_node 落库（SP-AGENT-005）
    if state.get("pending_confirm"):
        await store.set_pending_confirm(session_id, state.get("pending_args"))
    else:
        await store.set_pending_confirm(session_id, None)

    # 消息历史与短期上下文（TTL 30 分钟）
    reply = state.get("reply") or ""
    if reply:
        await repo.add_message(
            session_id, "assistant", reply,
            intent=state.get("intent"), conf=state.get("conf"),
            agent_route=state.get("route"),
        )
        ctx = await store.get_context(session_id)
        await store.set_context(
            session_id,
            ctx + [{"role": "user", "content": message},
                   {"role": "assistant", "content": reply}],
        )

    # done 事件（转人工 transfer 标记 / 工单号 / 错误兜底）
    if state.get("error_code"):
        data = {"error": _error_data(state["error_code"])}
    else:
        data = {
            "ticket_id": state.get("ticket_id"),
            "transfer": bool(state.get("transfer_needed")),
        }
    seq = await _emit(deps, session_id, "done", data)
    yield ("done", data, seq)
