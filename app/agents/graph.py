"""SP-AGENT-004 状态机编排（LangGraph）：入口 → 意图+路由 → 分支 Agent → 回复。

状态字段（规格）：`{messages, intent, conf, route, tool_calls, retrieved_docs,
ticket_id, transfer_needed, pending_confirm}`（+ session_id/user_id/message/reply）。

- CONFIRM 挂起：敏感操作（建单）设 `pending_confirm=true`，**未确认不得建单**；
  挂起期间新消息仅接受"确认/取消"（其余消息 → 拒绝处理话术）
- 每个节点产出 `_sse` 事件（intent/route/vision/retrieval/message），由
  chat_flow 适配层按 SP-SSE-001 顺序发流并持久化
- 异常节点不中断整条链：节点内 try/except → fallback 兜底回复 + error_code
- `execute_graph`：便捷入口（初始状态构造 + ainvoke），单轮无状态续跑
  （pending 挂起上下文由 chat_flow 从 Redis 读入，见 run_chat_flow）
"""
from __future__ import annotations

import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.qa_agent import generate_answer
from app.agents.router import route
from app.agents.tool_agent import (
    FakeToolParser,
    ToolArgsParser,
    extract_order_id,
    execute_query_order,
    validate_tool_args,
)
from app.agents.transfer_agent import generate_summary, mark_transfer
from app.intent.decision import Decision, decide
from app.intent.guard import should_transfer
from app.intent.labels import INVALID_INTENT
from app.retrieval.hybrid_search import hybrid_search
from app.security.injection import INJECTION_REPLY, detect_injection
from app.security.masking import mask_reply_text
from app.services.erp_sim import get_order
from app.services.llm import LLMUnavailableError
from app.services.refund_gateway import RefundGateway, ServiceRefundGateway

logger = logging.getLogger("app.agents.graph")

CLARIFY_REPLY = "抱歉，我暂时无法确定您的意图，请再详细说明一下您的问题。"
TRANSFER_REPLY = "已为您转接人工客服坐席 1001，请稍候。"
CONFIRM_REPLY = "该操作将创建退款申请单，请回复「确认」继续，或回复「取消」放弃。"
PENDING_DENY_REPLY = "您有一笔退款申请待确认，请回复「确认」或「取消」。"
FALLBACK_REPLY = "抱歉，系统暂时无法处理您的请求，请稍后重试。"
REFUND_CLARIFY_REPLY = "请提供您的订单号（例如 ORD-20260811-001）以便发起退款申请。"

_CONFIRM_RE = ("确认", "确定")
_CANCEL_RE = ("取消", "放弃")


class AgentState(TypedDict, total=False):
    """图状态（SP-AGENT-004）：字段均可序列化回放。

    注意：LangGraph 按本 schema 过滤状态键，未声明的键会被丢弃。
    """

    session_id: str
    user_id: str
    message: str
    messages: list[dict]
    attachments: list[dict]
    vision_text: str
    intent: str
    conf: float
    route: str | None
    tool_calls: list[dict]
    retrieved_docs: list[dict]
    ticket_id: str | None
    transfer_needed: bool
    pending_confirm: bool
    pending_args: dict | None
    reply: str | None
    rejected: bool
    error_code: int | None
    #: 节点产出的 SSE 事件（chat_flow 适配层消费）
    _sse: list[dict]


def _emit(state: AgentState, event: str, data: dict) -> None:
    state.setdefault("_sse", []).append({"event": event, "data": data})


def _is_confirm(text: str) -> bool:
    return any(text.strip().startswith(k) for k in _CONFIRM_RE)


def _is_cancel(text: str) -> bool:
    return any(text.strip().startswith(k) for k in _CANCEL_RE)


def _safe(fn):
    """节点包装：异常不中断整条链，走 fallback 兜底（T-AGENT-402）。"""

    async def wrapped(state: AgentState) -> dict:
        try:
            return await fn(state)
        except LLMUnavailableError:
            logger.warning("节点 %s 调用 LLM 不可用（5001）→ 兜底", fn.__name__)
            return {"reply": FALLBACK_REPLY, "error_code": 5001}
        except Exception as exc:  # noqa: BLE001
            logger.exception("节点 %s 异常 → 兜底", fn.__name__)
            return {"reply": FALLBACK_REPLY, "error_code": 5000, "error": str(exc)}

    return wrapped


def build_graph(deps: Any):
    """构建 LangGraph 状态机（节点直连既有模块，不引入 LangChain 抽象）。"""

    async def intent_node(state: AgentState) -> dict:
        result = await deps.classifier.predict(state["message"])
        intent, conf = result.intent, result.conf
        _emit(state, "intent", {"intent": intent, "conf": conf})
        return {"intent": intent, "conf": conf, "_sse": state["_sse"]}

    async def route_node(state: AgentState) -> dict:
        intent, conf = state["intent"], state["conf"]
        # 挂起检查：仅接受"确认/取消"
        if state.get("pending_args"):
            if _is_confirm(state["message"]):
                agent = "confirm"
            elif _is_cancel(state["message"]):
                agent = "cancel"
            else:
                agent = "pending_deny"
            reason = "pending_confirm"
            final_intent, final_conf = intent, conf
        elif intent == INVALID_INTENT:
            agent, reason, final_intent, final_conf = "clarify", "invalid_input", intent, conf
        else:
            decision = await decide(intent, conf, llm=deps.llm, text=state["message"])
            if decision.action == "route":
                final_intent, final_conf = decision.intent, decision.conf
            else:
                final_intent, final_conf = intent, conf
            if should_transfer(state["message"]):
                agent, reason = "transfer_agent", "abuse"
            elif decision.action == "route":
                agent = route(final_intent) or "clarify"
                reason = decision.reason
            else:
                agent, reason = "clarify", decision.reason
        _emit(state, "route", {"agent": agent, "reason": reason,
                               "intent": final_intent, "conf": final_conf})
        return {"route": agent, "intent": final_intent, "conf": final_conf, "_sse": state["_sse"]}

    async def vision_node(state: AgentState) -> dict:
        """图片附件 → mimo-v2.5 异步理解，注入检索 query（SP-CHAT-002）。"""
        vision_text = ""
        for att in state.get("attachments") or []:
            try:
                result = await deps.llm.vision(att["url"], "请描述这张图片中的信息内容。")
            except LLMUnavailableError:
                continue
            vision_text += result.content
            _emit(state, "vision", {"description": result.content, "model": result.model})
        return {"vision_text": vision_text, "_sse": state["_sse"]}

    async def qa_node(state: AgentState) -> dict:
        message = state["message"]
        if state.get("vision_text"):
            message = f"{message}\n{state['vision_text']}"
        search = await hybrid_search(
            message, deps.es, deps.embedding, top_k=deps.retrieval_top_k
        )
        docs = search["docs"][: deps.retrieval_top_k]
        _emit(state, "retrieval", {
            "docs": [{"chunk_id": d["chunk_id"], "title": d["title"], "score": d["score"]}
                     for d in docs],
            "strategy": search["strategy"], "count": len(docs),
        })
        result = await generate_answer(state["message"], docs, deps.llm)
        return {"retrieved_docs": docs, "reply": result.content, "rejected": result.rejected,
                "_sse": state["_sse"]}

    async def tool_node(state: AgentState) -> dict:
        """order_query → 工具调用（解析/校验/归属）；参数非法不调用真实服务 → 澄清。"""
        if detect_injection(state["message"]):  # SP-SEC-001：注入指令前置拦截，零调用
            return {"reply": INJECTION_REPLY, "tool_calls": []}
        order_id = extract_order_id(state["message"])
        if order_id is None:
            return {"reply": "请提供订单号（例如 ORD-20260811-001）以便查询。", "tool_calls": []}
        result = execute_query_order(order_id, state["user_id"])
        tool_call = {"tool": "query_order", "args": {"order_id": order_id}, "result": result}
        _emit(state, "tool_call", tool_call)
        if result["code"] == 4030:
            return {"reply": "无权访问该订单，请核对订单号。", "tool_calls": [tool_call]}
        if result["code"] == 4041:
            return {"reply": "未找到该订单，请核对订单号。", "tool_calls": [tool_call]}
        reply = (
            f"您的订单 {order_id} 当前状态：{result['data']['status']}，"
            f"物流信息：{result['data']['logistics']}。"
        )
        return {"reply": reply, "tool_calls": [tool_call], "_sse": state["_sse"]}

    async def refund_node(state: AgentState) -> dict:
        """refund → 提取订单号 → 组装建单参数（金额取订单实付，SP-REF-001）→
        CONFIRM 挂起（未确认不得建单）。"""
        if detect_injection(state["message"]):  # SP-SEC-001：注入指令不进入 CONFIRM/建单
            return {"reply": INJECTION_REPLY, "pending_args": None}
        order_id = extract_order_id(state["message"])
        if order_id is None:
            return {"reply": REFUND_CLARIFY_REPLY}
        order = get_order(order_id)
        if order is None:
            return {"reply": "未找到该订单，请核对订单号。"}
        if order.user_id != state["user_id"]:  # 防御性归属校验（SP-AGENT-003 口径）
            return {"reply": "无权对该订单发起退款申请，请核对订单号。"}
        args = {
            "order_id": order_id,
            "refund_type": "only_refund",
            "reason": "用户申请退款",
            "amount": order.amount,  # 从订单实付金额取值（SP-REF-001）
        }
        invalid = validate_tool_args("create_refund_request", args)
        if invalid:
            return {"reply": f"参数校验未通过：{invalid}（未创建任何申请单）"}
        state["pending_args"] = args
        _emit(state, "tool_call", {"tool": "create_refund_request",
                                   "args": args, "result": None, "pending": True})
        return {"pending_confirm": True, "pending_args": args, "reply": CONFIRM_REPLY,
                "_sse": state["_sse"]}

    async def confirm_node(state: AgentState) -> dict:
        """用户确认 → 建单（返回单号）；取消 → 放弃并澄清。"""
        args = state.get("pending_args") or {}
        if _is_cancel(state["message"]):
            return {"pending_confirm": False, "pending_args": None,
                    "reply": "已取消本次退款申请，如需要可随时再次发起。"}
        ticket = await deps.refund_gateway.create_request(
            user_id=state["user_id"],
            order_id=args.get("order_id", ""),
            refund_type=args.get("refund_type", "only_refund"),
            reason=args.get("reason", ""),
            amount=float(args.get("amount", 0.0)),
        )
        return {"pending_confirm": False, "pending_args": None, "ticket_id": ticket.ticket_id,
                "reply": f"退款申请已创建，单号 {ticket.ticket_id}，请耐心等待审核。"}

    async def cancel_node(state: AgentState) -> dict:
        return {"pending_confirm": False, "pending_args": None,
                "reply": "已取消本次退款申请，如需要可随时再次发起。"}

    async def pending_deny_node(state: AgentState) -> dict:
        return {"reply": PENDING_DENY_REPLY, "pending_confirm": True}

    async def transfer_node(state: AgentState) -> dict:
        summary = generate_summary(
            state.get("messages", []) + [{"role": "user", "content": state["message"]}],
            intent=state["intent"],
        )
        await mark_transfer(deps.store, state["session_id"], summary)
        return {"transfer_needed": True, "reply": TRANSFER_REPLY, "transfer_summary": summary}

    async def clarify_node(state: AgentState) -> dict:
        return {"reply": CLARIFY_REPLY}

    async def reply_node(state: AgentState) -> dict:
        # SP-SEC-002：统一脱敏（手机号 138****5678 / 订单号 ORD-****），
        # 在 SSE 下发与 PG/Redis 落库之前完成
        reply = mask_reply_text(state.get("reply") or FALLBACK_REPLY)
        _emit(state, "message", {"content": reply, "delta": True})
        _emit(state, "message", {"content": "", "delta": False})
        return {"reply": reply, "_sse": state["_sse"]}

    g = StateGraph(AgentState)
    g.add_node("intent", _safe(intent_node))
    g.add_node("route", _safe(route_node))
    g.add_node("vision", _safe(vision_node))
    g.add_node("qa", _safe(qa_node))
    g.add_node("tool", _safe(tool_node))
    g.add_node("refund", _safe(refund_node))
    g.add_node("confirm", _safe(confirm_node))
    g.add_node("cancel", _safe(cancel_node))
    g.add_node("pending_deny", _safe(pending_deny_node))
    g.add_node("transfer", _safe(transfer_node))
    g.add_node("clarify", _safe(clarify_node))
    g.add_node("reply", _safe(reply_node))
    g.add_edge(START, "intent")
    g.add_edge("intent", "route")
    g.add_conditional_edges(
        "route",
        lambda s: s.get("route", "clarify"),
        {
            "qa_agent": "vision",
            "tool_agent": "tool",
            "refund_agent": "refund",
            "transfer_agent": "transfer",
            "clarify": "clarify",
            "confirm": "confirm",
            "cancel": "cancel",
            "pending_deny": "pending_deny",
        },
    )
    for node in ("qa", "tool", "refund", "confirm", "cancel", "pending_deny", "transfer", "clarify"):
        g.add_edge(node, "reply")
    g.add_edge("vision", "qa")
    g.add_edge("reply", END)
    return g.compile()


async def execute_graph(
    deps: Any,
    *,
    session_id: str,
    user_id: str,
    message: str,
    attachments: list[dict] | None = None,
    pending: dict | None = None,
) -> dict:
    """便捷入口：构造初始状态并执行（单轮；挂起上下文由调用方传入）。"""
    ctx = await deps.store.get_context(session_id)
    initial: AgentState = {
        "session_id": session_id,
        "user_id": user_id,
        "message": message,
        "messages": ctx,
        "attachments": attachments or [],
        "pending_args": pending,
    }
    graph = build_graph(deps)
    final: AgentState = await graph.ainvoke(initial)
    return dict(final)
