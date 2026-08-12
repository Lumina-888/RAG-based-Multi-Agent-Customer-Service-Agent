"""SP-ING-003 索引写入（补充单元层，规格测试见 tests/integration/test_indexer.py）。

- T-ING-303 确定性 _id=doc_id-seq，写入计数正确
- T-ING-304 重索引覆盖旧数据（幂等）：删除残留 seq + 覆盖同 id，无重复文档
- T-ING-305 每条含 embedding（dim 与客户端一致）与元数据（embedding_ver 等）
- T-ING-306 embedding 失败 → 错误传播且不写 ES（旧数据保留）
"""
from __future__ import annotations

import pytest

from app.ingestion.indexer import EMBEDDING_VER, index_chunks
from app.ingestion.models import Chunk
from app.services.embedding import EmbeddingError, FakeEmbeddingClient


class FakeESClient:
    """内存版 ES：记录 ensure/delete/bulk，模拟 kb_chunks 的 _id 覆盖语义。"""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}
        self.ensure_dim: int | None = None
        self.ensure_calls = 0

    async def ensure_kb_index(self, dim: int = 1024) -> None:
        self.ensure_calls += 1
        self.ensure_dim = dim

    async def delete_by_doc_id(self, doc_id: str) -> None:
        self.docs = {k: v for k, v in self.docs.items() if v["doc_id"] != doc_id}

    async def bulk_index(self, docs: list[dict]) -> int:
        for d in docs:
            self.docs[d["_id"]] = {k: v for k, v in d.items() if k != "_id"}
        return len(docs)

    async def count_doc(self, doc_id: str) -> int:
        return sum(1 for v in self.docs.values() if v["doc_id"] == doc_id)


def _chunks(doc_id: str, n: int, text: str = "内容") -> list[Chunk]:
    return [
        Chunk(doc_id=doc_id, seq=i, title="手册", source="a.md", heading_path="甲 / 子",
              content=f"{text}-{i}", tokens=3)
        for i in range(n)
    ]


@pytest.mark.spec("SP-ING-003")
class TestIndexChunks:
    async def test_ing_303_deterministic_ids(self) -> None:
        es = FakeESClient()
        embedding = FakeEmbeddingClient(dim=1024)

        n = await index_chunks(_chunks("doc-x", 3), doc_id="doc-x", es=es, embedding=embedding)

        assert n == 3
        assert sorted(es.docs) == ["doc-x-0", "doc-x-1", "doc-x-2"]  # _id=doc_id-seq
        assert es.ensure_calls == 1
        assert es.ensure_dim == 1024  # dim 与 embedding 客户端一致

    async def test_ing_304_reindex_idempotent(self) -> None:
        es = FakeESClient()
        embedding = FakeEmbeddingClient(dim=1024)

        await index_chunks(_chunks("doc-y", 3, text="旧版"), doc_id="doc-y", es=es, embedding=embedding)
        assert await es.count_doc("doc-y") == 3

        # 重索引：内容变化 + 块数变少 → 无重复、旧内容被覆盖、残留 seq 被清理
        await index_chunks(_chunks("doc-y", 2, text="新版"), doc_id="doc-y", es=es, embedding=embedding)
        assert await es.count_doc("doc-y") == 2
        assert sorted(es.docs) == ["doc-y-0", "doc-y-1"]
        assert es.docs["doc-y-0"]["content"] == "新版-0"

    async def test_ing_305_metadata_and_embedding(self) -> None:
        es = FakeESClient()
        embedding = FakeEmbeddingClient(dim=1024)
        chunks = _chunks("doc-z", 1)
        chunks[0].content = "退款政策内容"

        await index_chunks(chunks, doc_id="doc-z", es=es, embedding=embedding)

        doc = es.docs["doc-z-0"]
        assert len(doc["embedding"]) == 1024  # bge-m3 dim=1024
        assert doc["embedding_ver"] == EMBEDDING_VER  # 模型升级时全量重建依据
        assert doc["title"] == "手册"
        assert doc["source"] == "a.md"
        assert doc["heading_path"] == "甲 / 子"
        assert doc["seq"] == 0
        assert doc["doc_id"] == "doc-z"
        assert doc["content"] == "退款政策内容"

    async def test_ing_306_embedding_failure_preserves_old_data(self) -> None:
        es = FakeESClient()
        embedding = FakeEmbeddingClient(dim=1024)

        await index_chunks(_chunks("doc-w", 2), doc_id="doc-w", es=es, embedding=embedding)
        assert await es.count_doc("doc-w") == 2

        broken = FakeEmbeddingClient(dim=1024, fail_times=1)
        with pytest.raises(EmbeddingError):
            await index_chunks(_chunks("doc-w", 2, text="新"), doc_id="doc-w", es=es, embedding=broken)
        # 失败发生在 delete 之前 → 旧数据原样保留
        assert await es.count_doc("doc-w") == 2

    async def test_ing_303_empty_chunks_noop(self) -> None:
        es = FakeESClient()
        n = await index_chunks([], doc_id="doc-v", es=es, embedding=FakeEmbeddingClient(dim=1024))
        assert n == 0
        assert es.ensure_calls == 0
