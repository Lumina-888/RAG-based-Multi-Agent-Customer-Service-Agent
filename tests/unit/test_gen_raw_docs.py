"""W1 知识库数据生成（G）单测：确定性、分类计数、格式对齐解析器、噪声验证。

- T-DATA-101 确定性：同一种子两次生成 → 内容完全一致
- T-DATA-102 分类计数：售后政策 30 / 商品手册 50 / FAQ 20
- T-DATA-103 格式对齐：商品手册含表格、FAQ 含 H2 问答、售后政策含 H1/H2
- T-DATA-104 噪声样本：掺入页码行/品牌水印，clean_markdown 可去除
- T-DATA-105 全量可解析：100 份文档 parse_markdown 均产出非空 sections
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from gen_raw_docs import (  # noqa: E402
    AFTER_SALES_COUNT,
    FAQ_COUNT,
    PRODUCT_COUNT,
    generate_docs,
)
from app.ingestion.parser import clean_markdown, parse_markdown  # noqa: E402

TOTAL = AFTER_SALES_COUNT + PRODUCT_COUNT + FAQ_COUNT


@pytest.fixture
def docs(tmp_path) -> list[Path]:
    return generate_docs(tmp_path, seed=42)


class TestRawDocs:
    def test_data_101_deterministic(self, tmp_path) -> None:
        a = generate_docs(tmp_path / "a", seed=42)
        b = generate_docs(tmp_path / "b", seed=42)
        assert [p.name for p in a] == [p.name for p in b]
        for pa, pb in zip(a, b):
            assert pa.read_text(encoding="utf-8") == pb.read_text(encoding="utf-8")

    def test_data_102_category_counts(self, docs: list[Path]) -> None:
        assert len(docs) == TOTAL
        names = [p.name for p in docs]
        assert sum(1 for n in names if n.startswith("售后政策-")) == AFTER_SALES_COUNT
        assert sum(1 for n in names if n.startswith("商品手册-")) == PRODUCT_COUNT
        assert sum(1 for n in names if n.startswith("FAQ-")) == FAQ_COUNT

    def test_data_103_formats_aligned(self, docs: list[Path]) -> None:
        product = next(p for p in docs if p.name.startswith("商品手册-"))
        text = product.read_text(encoding="utf-8")
        # H1 可能前有噪声行（页码），按行首匹配
        assert any(line.startswith("# ") for line in text.splitlines())
        assert "## 规格参数" in text
        assert "| 参数 | 数值 |" in text  # 表格保留（SP-ING-001）

        faq = next(p for p in docs if p.name.startswith("FAQ-"))
        faq_text = faq.read_text(encoding="utf-8")
        assert "## Q1：" in faq_text and "## Q10：" in faq_text

        after = next(p for p in docs if p.name.startswith("售后政策-"))
        after_text = after.read_text(encoding="utf-8")
        assert after_text.startswith("# ") and "## " in after_text

    def test_data_104_noise_removed_by_cleaner(self, docs: list[Path]) -> None:
        noisy = [p for p in docs if "第 1 页" in p.read_text(encoding="utf-8")]
        assert noisy, "应存在掺入页码噪声的样本"
        for path in noisy[:2]:
            raw = path.read_text(encoding="utf-8")
            cleaned = clean_markdown(raw)
            assert "第 1 页" not in cleaned  # 页码行去除
            assert "Page 1 of 8" not in cleaned
            # 品牌水印：被选中行重复 ≥3 次 → 全部去除；另一候选行本就未出现
            assert "智能优选电商" not in cleaned
            assert "内部资料" not in cleaned

    def test_data_105_all_parsable(self, docs: list[Path]) -> None:
        for path in docs:
            parsed = parse_markdown(path.read_text(encoding="utf-8"), source=path.name, version="1.0")
            assert parsed.sections, f"{path.name} 解析后无内容"
            assert parsed.title
