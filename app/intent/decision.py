"""SP-INT-003 置信度分级决策。

`decide(intent, conf, llm, text)` 按 fastText 置信度分级：
- conf ≥ 0.85 → `{action: "route", intent}`（不依赖 LLM，主备均不可用时仍可路由）
- 0.6 ≤ conf < 0.85 → LLM 二次确认（主模型 DeepSeek-V4-flash），以 LLM 结果路由；
  LLM 不可用/解析失败 → `{action: "clarify"}`
- conf < 0.6 → LLM 兜底分类（主→备降级由 SP-CFG-004 路由负责）；LLM 结果仍
  低置信或解析失败 → `{action: "clarify"}`
- 主备均不可用（5001）→ 统一降级 `{action: "clarify"}`
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.intent.labels import INTENT_LABELS
from app.services.llm import LLMUnavailableError

logger = logging.getLogger("app.intent.decision")

#: 意图标识正则（大小写不敏感，容许出现在句内）
_LABEL_RE = re.compile(r"\b(" + "|".join(INTENT_LABELS) + r")\b", re.IGNORECASE)

CONFIRM_PROMPT = (
    "你是客服意图确认助手。系统预判该消息意图为「{intent}」（置信度 {conf:.2f}）。"
    "请确认最终意图，只输出下列标识之一，不要输出任何其他内容：\n"
    "{labels}\n用户消息：{text}"
)
FALLBACK_PROMPT = (
    "你是客服意图分类助手。请将用户消息分类为下列意图之一，"
    "只输出意图标识，不要输出任何其他内容：\n"
    "{labels}\n用户消息：{text}"
)


class LLMProvider(Protocol):
    """LLM 封装协议（SP-CFG-004 的 LLMRouter 即满足）。"""

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any: ...


@dataclass
class Decision:
    """决策结果：action ∈ {route, clarify}；route 时带最终 intent 与 conf。"""

    action: str
    intent: str | None = None
    conf: float | None = None
    reason: str = ""

    def as_dict(self) -> dict:
        return {"action": self.action, "intent": self.intent, "conf": self.conf}


def parse_llm_intent(response: str | None) -> str | None:
    """从 LLM 回复中解析 6 类意图之一；无命中返回 None（解析失败）。"""
    if not response:
        return None
    match = _LABEL_RE.search(response)
    return match.group(1).lower() if match else None


def _labels_hint() -> str:
    return " / ".join(INTENT_LABELS)


async def _ask_llm(llm: LLMProvider, prompt: str) -> str | None:
    """调用 LLM（主→备降级由路由负责）；主备均不可用（5001）→ None。"""
    try:
        result = await llm.chat([{"role": "user", "content": prompt}])
        content = result.content if hasattr(result, "content") else str(result)
        return content.strip()
    except LLMUnavailableError:
        logger.warning("LLM 不可用（5001），意图确认降级 clarify")
        return None


async def decide(
    intent: str, conf: float, llm: LLMProvider | None = None, text: str = ""
) -> Decision:
    """置信度分级决策（阈值来自配置 intent_conf_high/mid，默认 0.85/0.6）。"""
    settings: Settings = get_settings()
    if conf >= settings.intent_conf_high:
        return Decision(action="route", intent=intent, conf=conf, reason="high_conf")
    if conf >= settings.intent_conf_mid:
        # 中置信 → LLM 二次确认（主模型），结果路由；不可用/解析失败 → 澄清
        if llm is None:
            return Decision(action="clarify", reason="llm_unavailable")
        response = await _ask_llm(
            llm,
            CONFIRM_PROMPT.format(
                intent=intent, conf=conf, labels=_labels_hint(), text=text
            ),
        )
        final_intent = parse_llm_intent(response)
        if final_intent is None:
            return Decision(action="clarify", reason="llm_unparseable")
        return Decision(action="route", intent=final_intent, conf=conf, reason="llm_confirm")
    # 低置信 → LLM 兜底分类（主→备降级）；仍低置信或解析失败 → 澄清
    if llm is None:
        return Decision(action="clarify", reason="llm_unavailable")
    response = await _ask_llm(
        llm, FALLBACK_PROMPT.format(labels=_labels_hint(), text=text)
    )
    final_intent = parse_llm_intent(response)
    if final_intent is None:
        return Decision(action="clarify", reason="llm_unparseable")
    return Decision(action="route", intent=final_intent, conf=conf, reason="llm_fallback")
