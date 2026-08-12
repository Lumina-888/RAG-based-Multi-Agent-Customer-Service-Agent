"""SP-ING-003 索引写入（需真实 ES）：T-ING-301 / T-ING-302。

- T-ING-301 写入计数正确（chunk 全部落库，含 embedding 与元数据）
- T-ING-302 同 doc_id 重复索引无重复文档（幂等覆盖）
"""
from __future__ import annotations

import pytest

from app.ingestion.chunker import chunk
from app.ingestion.indexer import index_chunks
from app.ingestion.parser import parse_markdown
from app.services.embedding import FakeEmbeddingClient
from app.services.es import ESClient

DOC_ID = "ing-test-doc"

MD = """# 售后政策
## 退货规则
| 场景 | 时限 | 说明 |
|---|---|---|
| 未发货 | 随时 | 仅支持仅退款 |
| 已签收 | 7 天 | 无理由退货 |

## 退款流程
退款将在 3~5 个工作日内原路退回，请耐心等待银行处理。
"""


@pytest.fixture
async def es(es_client: ESClient) -> ESClient:
    await es_client.delete_by_doc_id(DOC_ID)
    yield es_client
    await es_client.delete_by_doc_id(DOC_ID)


@pytest.mark.spec("SP-ING-003")
@pytest.mark.integration
class TestIndexerIntegration:
    async def test_ing_301_write_count_and_embedding(self, es: ESClient) -> None:
        doc = parse_markdown(MD, source="售后政策.md", version="1.0")
        chunks = chunk(doc, doc_id=DOC_ID)
        assert len(chunks) >= 2  # 多小节分块

        n = await index_chunks(chunks, doc_id=DOC_ID, es=es, embedding=FakeEmbeddingClient(dim=1024))

        assert n == len(chunks)
        assert await es.count_doc(DOC_ID) == len(chunks)

    async def test_ing_302_reindex_no_duplicates(self, es: ESClient) -> None:
        embedding = FakeEmbeddingClient(dim=1024)
        doc_v1 = parse_markdown(MD, source="售后政策.md", version="1.0")
        await index_chunks(chunk(doc_v1, doc_id=DOC_ID), doc_id=DOC_ID, es=es, embedding=embedding)
        assert await es.count_doc(DOC_ID) >= 2

        # 重索引：内容变化 + 块数减少 → 计数精确、无残留
        doc_v2 = parse_markdown("# 售后政策\n仅退款说明。", source="售后政策.md", version="2.0")
        chunks_v2 = chunk(doc_v2, doc_id=DOC_ID)
        await index_chunks(chunks_v2, doc_id=DOC_ID, es=es, embedding=embedding)

        assert await es.count_doc(DOC_ID) == len(chunks_v2)  # 无重复文档
