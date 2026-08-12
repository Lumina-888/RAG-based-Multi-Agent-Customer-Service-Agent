"""SP-EVAL-002 RAGAS 指标（faithfulness / answer_relevancy，真实 LLM 打分）。

- `faithfulness(answer, contexts, llm)`：回答中由上下文支撑的陈述占比（0~1）；
  LLM 失败 / 分数不可解析 → **规则兜底**：复用 `qa_agent.check_faithfulness`
  启发式（有有效 `[n]` 角标支撑的句子占比，技术债 #5 口径）
- `answer_relevancy(question, answer, llm)`：回答与问题的相关性（0~1）；
  无规则兜底，LLM 失败 / 不可解析 → `LLMUnavailableError`（评测脚本标记 skip）
- 无 `DEEPSEEK_API_KEY` 等场景由调用方按 T-RET-201 模式 skip；CI 单测注入 FakeLLM
"""
from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from app.agents.qa_agent import check_faithfulness
from app.core.config import get_settings
from app.services.llm import LLMUnavailableError, build_llm

logger = logging.getLogger("app.eval.ragas_eval")

#: 分数形态：纯数字（含负数）/ "score: 0.75" / "85 分" / JSON {"score": 0.9}
_NUMBER_RE = re.compile(r"(-?\d+(?:\.\d+)?)")

_FP_PROMPT = (
    "你是评测助手。判断以下回答中的陈述是否都能由给定上下文支撑。\n"
    "上下文：\n{contexts}\n\n回答：\n{answer}\n\n"
    "只输出一个 0~1 之间的分数（1=完全由上下文支撑，0=完全编造），不要输出其他内容。"
)
_RELEVANCY_PROMPT = (
    "你是评测助手。判断以下回答与用户问题的相关程度。\n"
    "问题：{question}\n\n回答：{answer}\n\n"
    "只输出一个 0~1 之间的分数（1=完全相关，0=完全不相关），不要输出其他内容。"
)


class LLMProvider(Protocol):
    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any: ...


def _parse_score(text: str) -> float | None:
    """从 LLM 回复中解析 0~1 分数；失败返回 None。

    - 支持 0~100 分制归一化（>2 视为百分制，如 "85 分" → 0.85）
    - 其余超界值钳制到 [0, 1]（如 "1.5" → 1.0）
    """
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    if value > 2.0:
        value /= 100.0
    return max(0.0, min(1.0, value))


async def faithfulness(
    answer: str, contexts: list[str], llm: LLMProvider | None = None
) -> float:
    """faithfulness：LLM 打分；失败/不可解析 → 规则兜底（不抛错，保证可评估）。"""
    if llm is None:
        llm = build_llm(get_settings())
    try:
        reply = await llm.chat(
            [
                {"role": "user", "content": _FP_PROMPT.format(
                    contexts="\n".join(f"[{i + 1}] {c}" for i, c in enumerate(contexts)),
                    answer=answer,
                )}
            ]
        )
        score = _parse_score(str(reply))
        if score is not None:
            return score
        logger.warning("faithfulness LLM 回复不可解析，走规则兜底: %r", str(reply)[:80])
    except LLMUnavailableError as exc:
        logger.warning("faithfulness LLM 不可用，走规则兜底: %s", exc)
    # 规则兜底：check_faithfulness（有有效 [n] 角标支撑的句子占比）
    return check_faithfulness(answer, [{"content": c} for c in contexts])


async def answer_relevancy(
    question: str, answer: str, llm: LLMProvider | None = None
) -> float:
    """answer_relevancy：LLM 打分；失败/不可解析 → LLMUnavailableError（调用方 skip）。"""
    if llm is None:
        llm = build_llm(get_settings())
    try:
        reply = await llm.chat(
            [
                {"role": "user", "content": _RELEVANCY_PROMPT.format(
                    question=question, answer=answer
                )}
            ]
        )
        score = _parse_score(str(reply))
        if score is not None:
            return score
    except LLMUnavailableError as exc:
        logger.warning("answer_relevancy LLM 不可用: %s", exc)
        raise
    raise LLMUnavailableError(f"answer_relevancy 分数不可解析: {str(reply)[:80]!r}")
