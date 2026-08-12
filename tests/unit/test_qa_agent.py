"""SP-AGENT-002 问答 Agent（离线单元层，FakeLLM 注入）。

- T-AGENT-211 faithful 校验：有 [n] 角标支撑的论点占比（门槛 ≥ 0.8 的前置）
- T-AGENT-212 回答生成：提示词强制引用来源（[n] 对应检索文档序号）
- T-AGENT-213 低相似度（top-1 < 0.45）→ 拒答模板，不调 LLM
"""
from __future__ import annotations

import pytest

from app.agents.qa_agent import check_faithfulness, generate_answer
from app.core.config import Settings
from app.services.llm import FakeLLM, LLMRouter


def _llm(replies: list[str] | None = None) -> LLMRouter:
    return LLMRouter(
        Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m"),
        FakeLLM("deepseek-v4-flash", replies=replies),
        FakeLLM("mimo-v2.5"),
        FakeLLM("mimo-v2.5"),
        backoff=0,
    )


DOCS = [
    {"chunk_id": "c1", "title": "售后政策", "content": "已签收 7 天内支持无理由退货。"},
    {"chunk_id": "c2", "title": "售后政策", "content": "退款 3~5 个工作日到账。"},
]


@pytest.mark.spec("SP-AGENT-002")
class TestQaAgent:
    def test_agent_211_faithfulness_gate(self) -> None:
        # 全角标支撑 → 1.0
        answer = "本商品支持 7 天无理由退货[1]，退款 3~5 个工作日到账[2]。"
        assert check_faithfulness(answer, DOCS) == 1.0
        # 部分支撑
        partial = "支持 7 天无理由退货[1]，质量非常好。"
        assert check_faithfulness(partial, DOCS) == 0.5
        # 无角标 / 角标越界 → 0
        assert check_faithfulness("质量非常好。", DOCS) == 0.0
        assert check_faithfulness("支持退货[9]。", DOCS) == 0.0  # 越界角标不算支撑
        assert check_faithfulness("", DOCS) == 0.0  # 空回答

    async def test_agent_212_answer_with_references(self) -> None:
        llm = _llm(replies=["支持 7 天无理由退货[1]，退款 3~5 个工作日到账[2]。"])
        result = await generate_answer("退货政策是什么", DOCS, llm)

        assert result.rejected is False
        assert "[1]" in result.content and "[2]" in result.content  # 引用角标
        user_msg = llm._main.calls[0]["messages"][1]  # 知识库注入在 user 消息
        assert "已签收 7 天内支持无理由退货" in user_msg["content"]
        assert "退货政策是什么" in llm._main.calls[0]["messages"][-1]["content"]  # 问题透传

    async def test_agent_213_reject_low_similarity(self) -> None:
        low_docs = [{"chunk_id": "c0", "title": "t", "content": "无关内容", "score": 0.2}]
        llm = _llm(replies=["不应被调用"])
        result = await generate_answer("随便问问", low_docs, llm)

        assert result.rejected is True
        assert "抱歉" in result.content  # 拒答模板，不编造
        assert llm._main.calls == []  # 拒答不调 LLM

    async def test_agent_213_boundary_accept(self) -> None:
        """top-1 = 0.45 恰好等于阈值 → 不拒答（走正常回答）。"""
        docs = [{"chunk_id": "c0", "title": "t", "content": "政策内容", "score": 0.45}]
        result = await generate_answer("政策是什么", docs, _llm(replies=["回答"]))
        assert result.rejected is False
