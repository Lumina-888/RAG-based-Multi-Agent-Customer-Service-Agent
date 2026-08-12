"""SP-EVAL-001 测试集加载（离线，tmp_path 手写文件）：T-EVAL-101/102。

- T-EVAL-101 加载计数：三种格式（intent.csv / retrieval.jsonl / chat_e2e.jsonl）
  合法行全部加载，字段解析正确
- T-EVAL-102 非法行跳过计数：缺字段 / 坏 JSON / 空列表 / 非法角色等行被跳过
  并准确计数报告（不抛错、不静默吞掉）
"""
from __future__ import annotations

import json

import pytest

from app.eval.case_loader import (
    ChatCase,
    IntentCase,
    RetrievalCase,
    load_chat_cases,
    load_intent_cases,
    load_retrieval_cases,
)

INTENT_CSV = """label,text
pre_sales,这个台灯多少钱
refund,我要申请退款
,缺标签行
pre_sales,
"""

RETRIEVAL_JSONL = "\n".join(
    [
        json.dumps({"query": "退款多久到账", "gold_docs": ["售后政策"]}),
        json.dumps({"query": "保温杯容量多大", "gold_docs": ["商品使用FAQ"]}),
        "not-a-json-line",
        json.dumps({"query": "缺 gold_docs"}),
        json.dumps({"gold_docs": ["x"], "query": ""}),
        json.dumps({"query": "空列表", "gold_docs": []}),
        json.dumps({"query": "非字符串 gold", "gold_docs": ["售后政策", 123]}),
    ]
)

CHAT_JSONL = "\n".join(
    [
        json.dumps(
            {
                "id": "ce-001", "path": "normal",
                "turns": [
                    {"role": "user", "content": "这个台灯多少钱"},
                    {"role": "assistant", "content": "89 元[1]"},
                ],
            }
        ),
        json.dumps(
            {"id": "ce-002", "path": "clarify", "turns": [{"role": "user", "content": "我要退款"}]}
        ),
        "not-a-json-line",
        json.dumps({"id": "ce-003", "path": "normal", "turns": []}),
        json.dumps({"id": "ce-004", "path": "normal", "turns": [{"role": "system", "content": "x"}]}),
        json.dumps({"turns": [{"role": "user", "content": "缺 id"}]}),
        json.dumps({"id": "ce-005", "path": "transfer", "turns": [{"role": "user", "content": ""}]}),
    ]
)


@pytest.fixture
def cases_dir(tmp_path) -> str:
    (tmp_path / "intent.csv").write_text(INTENT_CSV, encoding="utf-8")
    (tmp_path / "retrieval.jsonl").write_text(RETRIEVAL_JSONL, encoding="utf-8")
    (tmp_path / "chat_e2e.jsonl").write_text(CHAT_JSONL, encoding="utf-8")
    return str(tmp_path)


@pytest.mark.spec("SP-EVAL-001")
class TestCaseLoader:
    @pytest.mark.parametrize(
        "load_fn,kwargs",
        [
            (load_intent_cases, {}),
            (load_retrieval_cases, {}),
            (load_chat_cases, {}),
        ],
    )
    def test_ev_101_loading_counts(self, cases_dir: str, load_fn, kwargs) -> None:
        """合法行全部加载（含表头/注释行不计入跳过）。"""
        if load_fn is load_intent_cases:
            cases, skipped = load_intent_cases(f"{cases_dir}/intent.csv")
            assert len(cases) == 2 and skipped == 2
            assert isinstance(cases[0], IntentCase)
            assert cases[0].label == "pre_sales" and cases[0].text == "这个台灯多少钱"
        elif load_fn is load_retrieval_cases:
            cases, skipped = load_retrieval_cases(f"{cases_dir}/retrieval.jsonl")
            assert len(cases) == 2 and skipped == 5
            assert isinstance(cases[0], RetrievalCase)
            assert cases[0].query == "退款多久到账" and cases[0].gold_docs == ["售后政策"]
        else:
            cases, skipped = load_chat_cases(f"{cases_dir}/chat_e2e.jsonl")
            assert len(cases) == 2 and skipped == 5
            assert isinstance(cases[0], ChatCase)
            assert cases[0].case_id == "ce-001" and cases[0].path == "normal"
            assert cases[0].turns[0] == {"role": "user", "content": "这个台灯多少钱"}

    def test_ev_102_bad_rows_skipped(self, cases_dir: str) -> None:
        """非法行跳过计数准确（每种格式的坏行数）。"""
        _, skipped_intent = load_intent_cases(f"{cases_dir}/intent.csv")
        _, skipped_retrieval = load_retrieval_cases(f"{cases_dir}/retrieval.jsonl")
        _, skipped_chat = load_chat_cases(f"{cases_dir}/chat_e2e.jsonl")
        assert skipped_intent == 2
        assert skipped_retrieval == 5
        assert skipped_chat == 5

    def test_ev_102b_missing_file_raises(self, tmp_path) -> None:
        """文件不存在 → FileNotFoundError（不静默返回空）。"""
        with pytest.raises(FileNotFoundError):
            load_intent_cases(str(tmp_path / "nope.csv"))
