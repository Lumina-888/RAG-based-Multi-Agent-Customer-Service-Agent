"""SP-ING-002 结构感知分块：T-ING-201 ~ 203（规格）+ T-ING-204/205（补充）。

- T-ING-201 不跨 H1 标题：块内容只属于单一 H1，heading_path 元数据正确
- T-ING-202 重叠正确：相邻块重叠 50 token（同 H1 内），块长 300~500 token
- T-ING-203 FAQ 完整性：一条 FAQ（Q+A）不被拆进两个块
- T-ING-204 表格原子性：表格整体成块，不被硬切
- T-ING-205 空文档 / 空小节 → 无块
"""
from __future__ import annotations

import pytest

from app.ingestion.chunker import (
    _split_blocks,
    _split_text_at_tokens,
    _tail_text,
    chunk,
    count_tokens,
    tokenize,
)
from app.ingestion.models import Document, Section

#: 单次重复 ≈ 16 token（4 个四字词）
_PARA_REPEAT = " 商品编号 详情说明 使用指南 注意事项 "


def _para(n: int, marker: str = "") -> str:
    """构造 n*16 + len(marker) token 的段落。"""
    return marker + _PARA_REPEAT * n


def _doc(sections: list[Section]) -> Document:
    return Document(
        title="测试手册", source="test.md", version="1.0", sections=sections
    )


@pytest.mark.spec("SP-ING-002")
class TestChunker:
    def test_ing_201_chunks_do_not_cross_h1(self) -> None:
        doc = _doc(
            [
                Section(1, "甲", "甲", "\n\n".join(_para(5, f"A{i}") for i in range(6))),
                Section(2, "子", "甲 / 子", _para(20, "甲甲")),
                Section(1, "乙", "乙", _para(20, "乙乙")),
            ]
        )
        chunks = chunk(doc)

        assert len(chunks) >= 3
        # heading_path 元数据与内容归属一致
        by_path: dict[str, list[str]] = {}
        for c in chunks:
            by_path.setdefault(c.heading_path, []).append(c.content)
        assert "甲 / 子" in by_path
        # 每个块的归属标记只含本小节内容，不含其他 H1/H2 的标记
        markers_by_path = {"甲": [f"A{i}" for i in range(6)], "甲 / 子": ["甲甲"], "乙": ["乙乙"]}
        for path, contents in by_path.items():
            own = markers_by_path[path]
            for c in contents:
                assert any(m in c for m in own)  # 含本小节标记
                for other_path, others in markers_by_path.items():
                    if other_path != path:
                        assert not any(m in c for m in others)  # 不含他小节内容
        # seq 连续且 doc_id 携带
        assert [c.seq for c in chunks] == list(range(len(chunks)))
        assert all(c.doc_id == "" for c in chunks)  # 未指定 doc_id 时为空
        assert all(c.heading_path for c in chunks)

    def test_ing_202_overlap_and_length(self) -> None:
        doc = _doc([Section(1, "甲", "甲", "\n\n".join(_para(5) for _ in range(12)))])
        chunks = chunk(doc, size=400, overlap=50)

        assert len(chunks) >= 3
        for i, c in enumerate(chunks):
            assert c.heading_path == "甲"
            if i < len(chunks) - 1:
                # 非末块长度落在 300~500（默认 size=400）
                assert 300 <= c.tokens <= 500
            assert c.tokens == count_tokens(c.content)
        for i in range(len(chunks) - 1):
            # 相邻块重叠恰好 50 token
            assert tokenize(chunks[i + 1].content)[:50] == tokenize(chunks[i].content)[-50:]

    def test_ing_203_faq_not_split(self) -> None:
        faq_lines: list[str] = []
        for i in range(20):
            faq_lines.append(f"Q: 问题{i} 应该如何解决？")
            faq_lines.append(
                f"A: 答案{i}：请参照手册第 {i} 节操作，若仍有疑问请提交工单。"
                + "若仍有疑问请提交工单，客服会尽快处理。"
            )
        doc = _doc([Section(1, "常见问题", "常见问题", "\n".join(faq_lines))])
        chunks = chunk(doc, size=400, overlap=50)

        assert len(chunks) >= 3  # 总 token 数足够触发切分
        for i in range(10):
            q, a = f"Q: 问题{i} 应该如何解决？", f"答案{i}：请参照手册第 {i} 节操作"
            holders = [c for c in chunks if q in c.content]
            assert len(holders) == 1  # 一条 FAQ 只落在一个块
            assert a in holders[0].content  # Q 与 A 同块

    def test_ing_204_table_stays_atomic(self) -> None:
        rows = "\n".join(
            f"| {i} | 商品名称编号{i} 详细规格说明{i} 库存数量{i} |" for i in range(60)
        )
        table = "| 编号 | 名称 |\n| --- | --- |\n" + rows  # ≈ 500+ token，超出单块预算
        content = "\n\n".join([_para(10), _para(10), table, _para(10)])
        doc = _doc([Section(1, "库存", "库存", content)])
        chunks = chunk(doc, size=400, overlap=50)

        table_chunks = [c for c in chunks if "| 编号 | 名称 |" in c.content]
        assert len(table_chunks) == 1  # 表格整体在单块内
        assert "| 59 |" in table_chunks[0].content
        assert "| 59 |" in table_chunks[0].content and "| 0 |" in table_chunks[0].content
        others = [c for c in chunks if c is not table_chunks[0]]
        assert all("|" not in c.content for c in others)  # 表格未被切碎

    def test_ing_205_empty_document(self) -> None:
        assert chunk(_doc([])) == []
        assert chunk(_doc([Section(1, "空", "空", "")])) == []
        assert chunk(_doc([Section(1, "空", "空", "   \n  ")])) == []

    def test_ing_202_default_size(self) -> None:
        """默认 size=400 / overlap=50，与显式调用一致。"""
        doc = _doc([Section(1, "甲", "甲", "\n\n".join(_para(5) for _ in range(12)))])
        assert chunk(doc) == chunk(doc, size=400, overlap=50)

    # ---------- 边界分支补充（覆盖率） ----------

    def test_ing_206_hard_split_oversize_paragraph(self) -> None:
        """单段超预算 → 按 token 硬切；无余量段落直接跳过。"""
        # 480 token 段落：先切 400 成块，余 80 进下一块
        doc = _doc([Section(1, "甲", "甲", _para(30))])
        chunks = chunk(doc)
        assert len(chunks) == 2
        assert chunks[0].tokens == 400
        assert chunks[1].tokens == 80 + 50  # 重叠 50 + 余量 80

        # 恰好 400 token 段落（无余量）：只产一块
        doc2 = _doc([Section(1, "甲", "甲", "词" * 400)])
        chunks2 = chunk(doc2)
        assert len(chunks2) == 1
        assert chunks2[0].content == "词" * 400

    def test_ing_206_blockquote_and_blank_in_faq(self) -> None:
        """引用块为原子块；FAQ 内空行不打断 Q/A 关联。"""
        doc = _doc([Section(1, "说明", "说明", "> 引用内容\n普通段落\nQ: 问题甲？\n\nA: 答案甲。")])
        chunks = chunk(doc)
        quoted = [c for c in chunks if "引用内容" in c.content]
        assert len(quoted) == 1
        assert "> 引用内容" in quoted[0].content
        q = [c for c in chunks if "问题甲" in c.content]
        assert len(q) == 1 and "答案甲" in q[0].content  # 空行未拆散 Q/A

    def test_ing_206_table_then_paragraph_no_blank(self) -> None:
        """表格行后紧跟普通行（无空行）→ 表格块正常闭合（不吞并段落）。"""
        blocks = _split_blocks("| 编号 | 名称 |\n| --- | --- |\n正文内容\n| 2 | 乙 |")
        assert [k for k, _ in blocks] == ["table", "para", "table"]

    def test_ing_206_overlap_zero(self) -> None:
        """overlap=0 → 无重叠尾（块间不重复）。"""
        doc = _doc([Section(1, "甲", "甲", "\n\n".join(_para(5, f"P{i}") for i in range(12)))])
        chunks = chunk(doc, size=400, overlap=0)
        assert len(chunks) >= 3
        assert tokenize(chunks[1].content)[:50] != tokenize(chunks[0].content)[-50:]

    def test_ing_206_atomic_block_in_overlap_window(self) -> None:
        """原子块（FAQ）位于窗口尾部且未超重叠预算 → 整体进入重叠窗口。"""
        faq = "Q: 测试问题？\nA: 这是测试答案内容，用于填充FAQ原子块的剩余预算部分。"
        content = "\n\n".join([_para(20), faq, "| 编号 | 名称 |\n" + "\n".join(
            f"| {i} | 商品名称编号{i} 详细规格说明{i} |" for i in range(25)
        ), _para(10)])
        doc = _doc([Section(1, "甲", "甲", content)])
        chunks = chunk(doc)
        assert len(chunks) >= 3
        # FAQ 整体进入下一块（重叠窗口内 Q/A 连续未拆散）
        assert "Q: 测试问题？\nA: 这是测试答案内容" in chunks[1].content

    def test_ing_206_split_helpers(self) -> None:
        """token 级切片辅助函数（防御性分支）。"""
        assert _split_text_at_tokens("甲乙丙", 0) == ("", "甲乙丙")
        assert _split_text_at_tokens("甲乙丙", 5) == ("甲乙丙", "")
        assert _tail_text("甲乙丙", 0) == ""
        assert _tail_text("甲乙", 5) == "甲乙"
        blocks = _split_blocks("普通行\n| 表 |\nQ: 问？\nA: 答。\n> 引用")
        assert [k for k, _ in blocks] == ["para", "table", "faq"]  # 引用行续接 FAQ 块
