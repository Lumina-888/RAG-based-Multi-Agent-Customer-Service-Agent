"""对话编排（SP-CHAT / SP-SSE）：intent → route → (vision) → (retrieval) → message → done。

事件协议（SP-SSE-001）：
- 顺序固定：intent（fastText 首响）→ route（LLM 修正后的最终 intent/conf）→
  (vision，图片附件异步理解) → (retrieval) → message(delta) → done
- 澄清路径：intent → route → message → done（无 retrieval）
- 转人工路径：intent → route → message → done（done.transfer=true）
- 错误路径：任何异常仍发送 done，data 带 error{code, message}（LLM 不可用 5001）
- 事件序列持久化至 Redis（session:{id}:events）供断线重放（Last-Event-ID）

路由（M4 内联简化口径，M5 交付 SP-AGENT-001 LangGraph 编排后替换）：
- pre_sales / after_sales / order_query / refund → qa_agent（检索 + LLM 回答）
- complaint / human → transfer_agent（转人工）
- 情绪升级（辱骂/重复标点，SP-INT-004）→ transfer_agent
- 低相似度（top-1 < 0.45）→ 拒答模板（SP-INT-004，不编造）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.core.config import Settings, get_settings
from app.intent.decision import Decision, decide
from app.intent.guard import should_reject, should_transfer
from app.intent.labels import INVALID_INTENT
from app.ingestion.images import VISION_PROMPT
from app.retrieval.hybrid_search import hybrid_search
from app.services.llm import LLMUnavailableError

logger = logging.getLogger("app.services.chat_flow")

#: M4 内联路由表（M5 替换为 SP-AGENT-001）
INTENT_TO_AGENT = {
    "pre_sales": "qa_agent",
    "after_sales": "qa_agent",
    "order_query": "qa_agent",
    "refund": "qa_agent",
    "complaint": "transfer_agent",
    "human": "transfer_agent",
}

CLARIFY_REPLY = "抱歉，我暂时无法确定您的意图，请再详细说明一下您的问题。"
TRANSFER_REPLY = "已为您转接人工客服坐席 1001，请稍候。"
REJECT_REPLY = (
    "抱歉，我没有在知识库中找到相关的可靠答案，请换个方式描述，或转人工客服咨询。"
)
SYSTEM_PROMPT = (
    "你是电商平台智能客服。请基于检索到的知识库内容回答用户问题；"
    "每个事实性论点用 [n] 标注来源；知识库未覆盖的内容不要编造。"
)


@dataclass
class ChatEvent:
    """SSE 事件：`event` 名 + `data`（合法 JSON）+ 持久化序号（id/Last-Event-ID）。"""

    event: str
    data: dict
    seq: int


async def _emit(
    deps: Any, session_id: str, event: str, data: dict
) -> ChatEvent:
    """持久化并产出事件（SP-SSE-001：事件序列持久化至 session:{id}:events）。"""
    seq = await deps.store.append_event(session_id, {"event": event, "data": data})
    return ChatEvent(event=event, data=data, seq=seq)


async def run_chat_flow(
    deps: Any,
    session_id: str,
    message: str,
    attachments: list[dict] | None = None,
    user_id: str = "anonymous",
) -> AsyncIterator[ChatEvent]:
    """一次对话请求的完整事件流（保证以 done 结尾，含错误兜底）。"""
    settings: Settings = get_settings()
    repo = deps.repo
    await repo.ensure_session(session_id, user_id)
    await repo.add_message(session_id, "user", message)

    try:
        # ---- intent 事件（fastText 首响，P95 < 2s 预算内）----
        intent_result = await deps.classifier.predict(message)
        intent, conf = intent_result.intent, intent_result.conf
        yield await _emit(deps, session_id, "intent", {"intent": intent, "conf": conf})

        # ---- 路由决策（SP-INT-003 置信度分级；非法输入直接澄清）----
        final_intent, final_conf = intent, conf
        if intent == INVALID_INTENT:
            decision = Decision(action="clarify", reason="invalid_input")
        else:
            decision = await decide(intent, conf, llm=deps.llm, text=message)
            if decision.action == "route":
                final_intent, final_conf = decision.intent, decision.conf

        # 情绪升级守卫（辱骂/高强度重复标点，SP-INT-004）→ 转人工
        if should_transfer(message):
            agent, reason = "transfer_agent", "abuse"
        elif decision.action == "route":
            agent = INTENT_TO_AGENT.get(final_intent, "qa_agent")
            reason = decision.reason
        else:
            agent, reason = "clarify", decision.reason

        # ---- route 事件（携带 LLM 修正后的最终 intent/conf）----
        yield await _emit(
            deps, session_id, "route",
            {"agent": agent, "reason": reason, "intent": final_intent, "conf": final_conf},
        )

        if agent == "transfer_agent":
            await repo.add_message(
                session_id, "assistant", TRANSFER_REPLY, final_intent, final_conf, agent
            )
            yield await _emit(deps, session_id, "message", {"content": TRANSFER_REPLY, "delta": True})
            yield await _emit(deps, session_id, "message", {"content": "", "delta": False})
            yield await _emit(deps, session_id, "done", {"ticket_id": None, "transfer": True})
            return

        if agent == "clarify":
            await repo.add_message(
                session_id, "assistant", CLARIFY_REPLY, final_intent, final_conf, agent
            )
            yield await _emit(deps, session_id, "message", {"content": CLARIFY_REPLY, "delta": True})
            yield await _emit(deps, session_id, "message", {"content": "", "delta": False})
            yield await _emit(deps, session_id, "done", {"ticket_id": None, "transfer": False})
            return

        # ---- vision 事件（图片附件 → mimo-v2.5 异步理解，不影响首响）----
        vision_text = ""
        if attachments and deps.llm is not None:
            for att in attachments:
                try:
                    result = await deps.llm.vision(att["url"], VISION_PROMPT)
                except LLMUnavailableError:
                    logger.warning("vision 理解失败，跳过图片 %s", att.get("url"))
                    continue
                vision_text += result.content
                yield await _emit(
                    deps, session_id, "vision",
                    {"description": result.content, "model": result.model},
                )

        # ---- retrieval 事件（qa 路径）----
        query = f"{message}\n{vision_text}".strip() if vision_text else message
        search = await hybrid_search(
            query, deps.es, deps.embedding, top_k=deps.retrieval_top_k
        )
        docs = [
            {"chunk_id": d["chunk_id"], "title": d["title"], "score": d["score"]}
            for d in search["docs"][: deps.retrieval_top_k]
        ]
        yield await _emit(
            deps, session_id, "retrieval",
            {"docs": docs, "strategy": search["strategy"], "count": len(docs)},
        )

        # 拒答（SP-INT-004）：知识库 top-1 相似度低于阈值 → 拒答模板，不编造
        if search["docs"] and should_reject(search["docs"][0]["score"]):
            await repo.add_message(
                session_id, "assistant", REJECT_REPLY, final_intent, final_conf, agent
            )
            yield await _emit(deps, session_id, "message", {"content": REJECT_REPLY, "delta": True})
            yield await _emit(deps, session_id, "message", {"content": "", "delta": False})
            yield await _emit(deps, session_id, "done", {"ticket_id": None, "transfer": False})
            return

        # ---- 生成回答（主 → 备降级；主备均失败 → 5001）----
        context = "\n".join(f"[{i + 1}] {d['content']}" for i, d in enumerate(search["docs"]))
        reply = await deps.llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"知识库：\n{context}\n\n问题：{message}"},
            ]
        )
        content = reply.content
        await repo.add_message(
            session_id, "assistant", content, final_intent, final_conf, agent
        )
        yield await _emit(deps, session_id, "message", {"content": content, "delta": True})
        yield await _emit(deps, session_id, "message", {"content": "", "delta": False})

        # 短期上下文刷新（TTL 30 分钟，仅影响上下文注入）
        ctx = await deps.store.get_context(session_id)
        await deps.store.set_context(
            session_id,
            ctx
            + [{"role": "user", "content": message}, {"role": "assistant", "content": content}],
        )

        yield await _emit(deps, session_id, "done", {"ticket_id": None, "transfer": False})
    except LLMUnavailableError:
        yield await _emit(
            deps, session_id, "done",
            {"error": {"code": 5001, "message": "LLM 服务不可用，请稍后重试"}},
        )
    except Exception as exc:  # noqa: BLE001 - 流开始后任何异常仍必须发送 done
        logger.exception("对话流程异常 session_id=%s", session_id)
        yield await _emit(
            deps, session_id, "done",
            {"error": {"code": 5000, "message": f"内部错误: {exc}"}},
        )
