"""SP-EVAL-002 RAGAS 指标（LLM 打分，FakeLLM 注入零网络）：T-EVAL-202~205。

- T-EVAL-202 faithfulness：LLM 返回分数被解析（含 "score: 0.75" 等文本形态）
- T-EVAL-203 faithfulness 规则兜底：LLM 失败 → 复用 `check_faithfulness` 启发式
- T-EVAL-204 answer_relevancy：LLM 分数解析
- T-EVAL-205 解析失败/LLM 不可用 → answer_relevancy 抛 LLMUnavailableError（调用方 skip）
"""
from __future__ import annotations

import pytest

from app.eval.ragas_eval import answer_relevancy, faithfulness
from app.services.llm import FakeLLM, LLMUnavailableError

CONTEXTS = [
    "退款将在 3~5 个工作日内原路退回，请耐心等待。",
    "已签收 7 天内支持无理由退货。",
]


@pytest.mark.spec("SP-EVAL-002")
class TestRagasEval:
    async def test_ev_202_faithfulness_parses_score(self) -> None:
        llm = FakeLLM(model="fake", replies=["0.8"])
        assert await faithfulness("退款 3~5 天到账。", CONTEXTS, llm) == pytest.approx(0.8)
        # 文本包裹形态："score: 0.75"
        llm = FakeLLM(model="fake", replies=["score: 0.75"])
        assert await faithfulness("退款 3~5 天到账。", CONTEXTS, llm) == pytest.approx(0.75)
        # 0~100 分制 → 归一化到 0~1
        llm = FakeLLM(model="fake", replies=["85 分"])
        assert await faithfulness("退款 3~5 天到账。", CONTEXTS, llm) == pytest.approx(0.85)

    async def test_ev_203_faithfulness_rule_fallback(self) -> None:
        """LLM 失败 → 规则兜底（check_faithfulness：有有效 [n] 角标的句子占比）。"""
        llm = FakeLLM(model="fake", fail_times=1)
        answer = "退款 3~5 个工作日到账[1]，7 天内可无理由退货[2]。\n以上内容仅供参考。"
        score = await faithfulness(answer, CONTEXTS, llm)
        assert score == pytest.approx(2 / 3)  # 3 句中有 2 句带有效角标

    async def test_ev_204_answer_relevancy_parses_score(self) -> None:
        llm = FakeLLM(model="fake", replies=["0.7"])
        assert await answer_relevancy("退款多久到账？", "3~5 个工作日。", llm) == pytest.approx(0.7)
        llm = FakeLLM(model="fake", replies=['{"score": 0.9}'])
        assert await answer_relevancy("这个台灯多少钱？", "89 元。", llm) == pytest.approx(0.9)

    async def test_ev_205_relevancy_unparseable_raises(self) -> None:
        # 不可解析（非数字）→ LLMUnavailableError（无规则兜底，调用方标记 skip）
        llm = FakeLLM(model="fake", replies=["无法评估"])
        with pytest.raises(LLMUnavailableError):
            await answer_relevancy("问题", "回答", llm)
        # LLM 本身不可用 → 同样抛错
        llm = FakeLLM(model="fake", fail_times=1)
        with pytest.raises(LLMUnavailableError):
            await answer_relevancy("问题", "回答", llm)

    async def test_ev_206_score_clamped_to_unit_interval(self) -> None:
        llm = FakeLLM(model="fake", replies=["1.5"])
        assert await faithfulness("回答", CONTEXTS, llm) == pytest.approx(1.0)
        llm = FakeLLM(model="fake", replies=["-0.2"])
        assert await answer_relevancy("问题", "回答", llm) == pytest.approx(0.0)
