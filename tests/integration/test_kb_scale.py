"""W1 知识库扩容集成验证（ES 守卫）：100 份文档 解析→分块→索引→检索。

- T-DATA-201 全量索引：100 份生成文档 chunk 全部写入 ES（FakeEmbedding dim=1024）
- T-DATA-202 检索可用：hybrid_search 对 售后/商品 查询均返回结果（doc_id 对齐）
- 测试后按 doc_id 清理（幂等索引口径：doc_id = 文件名 stem）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from gen_raw_docs import generate_docs  # noqa: E402

from app.ingestion.chunker import chunk  # noqa: E402
from app.ingestion.indexer import index_chunks  # noqa: E402
from app.ingestion.parser import parse_markdown  # noqa: E402
from app.retrieval.hybrid_search import hybrid_search  # noqa: E402
from app.services.embedding import FakeEmbeddingClient  # noqa: E402


@pytest.mark.spec("SP-ING-003")
@pytest.mark.integration
class TestKbScale:
    async def test_data_201_202_index_all_and_search(
        self, es_client, tmp_path
    ) -> None:
        embedding = FakeEmbeddingClient(dim=1024)
        docs = generate_docs(tmp_path, seed=42)
        doc_ids = [p.stem for p in docs]
        try:
            for path in docs:
                doc_id = path.stem
                await es_client.delete_by_doc_id(doc_id)
                parsed = parse_markdown(path.read_text(encoding="utf-8"), source=path.name, version="1.0")
                await index_chunks(
                    chunk(parsed, doc_id=doc_id), doc_id=doc_id, es=es_client, embedding=embedding
                )

            total = await es_client.count()
            assert total > 0
            for sample in doc_ids[:5]:
                assert await es_client.count_doc(sample) > 0

            # T-DATA-202：混合检索返回结果（doc_id 与生成文件名 stem 对齐）
            for q in ("退款多久到账", "保温杯容量多大", "常见问题"):
                result = await hybrid_search(q, es_client, embedding=embedding, strategy="rrf", top_k=5)
                assert result["docs"], f"查询 {q!r} 无结果"
                assert all(d["doc_id"] for d in result["docs"])
        finally:
            for doc_id in doc_ids:
                await es_client.delete_by_doc_id(doc_id)
