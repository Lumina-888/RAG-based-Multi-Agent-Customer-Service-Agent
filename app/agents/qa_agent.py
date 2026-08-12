"""SP-AGENT-002 问答 Agent：基于检索结果生成回答，强制引用来源。

- 每个事实性论点标注来源角标 `[n]`（n 对应检索文档，由提示词约束）
- 无来源支撑的陈述不得出现（提示词约束 + `check_faithfulness` 启发式校验）
- 低相似度（top-1 < RETRIEVAL_REJECT_THRESHOLD，默认 0.45）→ 拒答模板，不编造
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.intent.guard import should_reject
from app.security.injection import build_user_turn

#: 强制引用系统提示词（SP-AGENT-002）
QA_SYSTEM_PROMPT = (
    "你是电商平台智能客服。请严格基于以下知识库内容回答用户问题：\n"
    "1) 每个事实性论点必须用 [n] 角标标注来源（n 对应知识库条目序号）；\n"
    "2) 没有来源支撑的陈述不得出现；\n"
    "3) 知识库未覆盖的内容不要编造，如实说明。"
)

REJECT_REPLY = (
    "抱歉，我没有在知识库中找到相关的可靠答案，请换个方式描述，或转人工客服咨询。"
)

#: 句末标点（含中文逗号——按子句切分，faithful 校验到子句粒度）
_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;，,、\n]+")
#: 来源角标：[n]
_REF_RE = re.compile(r"\[(\d+)\]")


@dataclass
class QaResult:
    """问答结果：回答内容 + 是否触发拒答。"""

    content: str
    rejected: bool = False


class LLMProvider(Protocol):
    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any: ...


def check_faithfulness(answer: str, docs: list[dict]) -> float:
    """启发式 faithful 校验：有有效 [n] 角标支撑的句子占比（0~1）。

    - 按句切分；含 `[n]` 且 1 ≤ n ≤ len(docs) 的句子计为"有支撑"
    - 角标越界 / 无角标句子不计支撑；空回答返回 0
    - 严格 RAGAS faithfulness 指标归 M7 评测体系
    """
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(answer) if s.strip()]
    if not sentences:
        return 0.0
    supported = 0
    for sentence in sentences:
        refs = [int(n) for n in _REF_RE.findall(sentence)]
        if refs and any(1 <= n <= len(docs) for n in refs):
            supported += 1
    return supported / len(sentences)


def _format_context(docs: list[dict]) -> str:
    return "\n".join(f"[{i + 1}] {d['content']}" for i, d in enumerate(docs))


async def generate_answer(
    question: str,
    docs: list[dict],
    llm: LLMProvider,
    reject_threshold: float | None = None,
) -> QaResult:
    """生成带强制引用的回答；top-1 相似度低于阈值 → 拒答模板（不调 LLM）。"""
    if not docs:
        return QaResult(content=REJECT_REPLY, rejected=True)
    top1_score = docs[0].get("score")
    if top1_score is not None and should_reject(float(top1_score), threshold=reject_threshold):
        return QaResult(content=REJECT_REPLY, rejected=True)
    result = await llm.chat(
        [
            {"role": "system", "content": QA_SYSTEM_PROMPT},
            # 分隔标记（SP-SEC-001）：用户输入与系统提示词之间显式隔离，
            # 注入指令仅视为数据
            {"role": "user", "content": f"知识库：\n{_format_context(docs)}\n\n{build_user_turn(question)}"},
        ]
    )
    content = result.content if hasattr(result, "content") else str(result)
    return QaResult(content=content.strip())
