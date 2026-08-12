"""SP-AGENT-002 问答 Agent（集成）：T-AGENT-201/202/203。

- T-AGENT-201 回答中引用角标 [n] 存在（FakeLLM 注入，检索走真实 ES）
- T-AGENT-202 低相似度（无命中）→ 拒答模板，不编造
- T-AGENT-203 faithfulness 门槛 ≥ 0.8（check_faithfulness 校验）
"""
from __future__ import annotations

import pytest

from app.agents.qa_agent import check_faithfulness, generate_answer
from app.core.config import Settings
from app.retrieval.hybrid_search import hybrid_search
from app.services.embedding import FakeEmbeddingClient
from app.services.llm import FakeLLM, LLMRouter


def _llm(replies: list[str] | None = None) -> LLMRouter:
    return LLMRouter(
        Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m"),
        FakeLLM("deepseek-v4-flash", replies=replies),
        FakeLLM("mimo-v2.5"),
        FakeLLM("mimo-v2.5"),
        backoff=0,
    )


@pytest.mark.spec("SP-AGENT-002")
@pytest.mark.integration
class TestQaAgentIntegration:
    async def test_agent_201_reference_citation(self, kb) -> None:
        """检索真实 ES 文档 → 回答携带 [n] 引用角标。"""
        search = await hybrid_search("退货", kb, embedding=FakeEmbeddingClient(dim=1024), top_k=5)
        docs = search["docs"]
        assert docs, "检索应有结果"

        llm = _llm(replies=["已签收 7 天内支持无理由退货[1]，退款 3~5 个工作日到账[2]。"])
        result = await generate_answer("退货政策是什么", docs, llm)

        assert result.rejected is False
        assert "[1]" in result.content and "[2]" in result.content  # T-AGENT-201 引用角标

    async def test_agent_202_reject_no_match(self, kb) -> None:
        """知识库无命中 → 拒答模板，不编造。"""
        search = await hybrid_search("qqqqqqzzzzzz", kb, embedding=FakeEmbeddingClient(dim=1024))
        llm = _llm(replies=["不应被调用"])
        result = await generate_answer("不存在的内容", search["docs"], llm)

        assert result.rejected is True
        assert "抱歉" in result.content  # 拒答模板（T-AGENT-202）
        assert llm._main.calls == []  # 拒答不调 LLM

    async def test_agent_203_faithfulness_gate(self, kb) -> None:
        """faithfulness ≥ 0.8：回答论点均有 [n] 角标支撑。"""
        search = await hybrid_search("退货", kb, embedding=FakeEmbeddingClient(dim=1024), top_k=5)
        docs = search["docs"]
        llm = _llm(replies=["已签收 7 天内支持无理由退货[1]，运费由平台承担[1]。"])
        result = await generate_answer("退货政策是什么", docs, llm)

        assert check_faithfulness(result.content, docs) >= 0.8  # T-AGENT-203
