"""SP-ING-003 索引写入 ES：幂等（`_id=doc_id-seq` 确定性生成 + 重索引前清理残留）。

- 每条 chunk 含 embedding（bge-m3，dim 与客户端一致）与元数据字段
  （含 `embedding_ver`：模型升级时按版本全量重建索引）
- 顺序：ensure 索引 → embedding 化（失败则不动 ES，旧数据保留）→
  清理旧 doc_id → bulk 覆盖写入
"""
from __future__ import annotations

from typing import Any, Protocol

from app.ingestion.models import Chunk

#: embedding 版本标识：bge-m3 模型升级时递增并全量重建（SP-ING-003）
EMBEDDING_VER = "bge-m3-v1"


class EmbeddingClient(Protocol):
    """embedding 客户端协议（SP-CFG-004 同模式，Fake 可注入）。"""

    model: str
    dim: int

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]: ...


class ESWriter(Protocol):
    """ES 写入协议：ensure / 清理 / bulk（FakeES 可注入）。"""

    async def ensure_kb_index(self, dim: int = 1024) -> None: ...

    async def delete_by_doc_id(self, doc_id: str) -> None: ...

    async def bulk_index(self, docs: list[dict]) -> int: ...


async def index_chunks(
    chunks: list[Chunk],
    doc_id: str,
    es: ESWriter,
    embedding: EmbeddingClient,
    embedding_ver: str = EMBEDDING_VER,
    meta: dict[str, Any] | None = None,
) -> int:
    """幂等写入：返回成功写入条数；空输入为 no-op。"""
    if not chunks:
        return 0
    await es.ensure_kb_index(dim=embedding.dim)
    vectors = await embedding.embed([c.content for c in chunks])
    await es.delete_by_doc_id(doc_id)
    docs: list[dict[str, Any]] = []
    for c, vec in zip(chunks, vectors):
        doc: dict[str, Any] = {
            "_id": f"{doc_id}-{c.seq}",  # 确定性 _id → 重复索引覆盖旧数据
            "doc_id": doc_id,
            "title": c.title,
            "source": c.source,
            "heading_path": c.heading_path,
            "seq": c.seq,
            "content": c.content,
            "embedding": vec,
            "embedding_ver": embedding_ver,
        }
        if meta:
            doc.update(meta)
        docs.append(doc)
    return await es.bulk_index(docs)
