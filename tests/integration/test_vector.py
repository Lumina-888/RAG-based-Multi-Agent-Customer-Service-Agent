"""SP-RET-002 向量检索（需 ES）：T-RET-201/202。

- T-RET-201 中文语义近义查询（"退货" ↔ "退款"）能召回 —— 需真实 bge-m3（
  EMBEDDING_API_KEY），未配置时跳过
- T-RET-202 维度与 embedding 模型一致（dim=1024，写入 ES 由 mapping 校验）
"""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.ingestion.chunker import chunk
from app.ingestion.indexer import index_chunks
from app.ingestion.parser import parse_markdown
from app.retrieval.hybrid_search import vector_search
from app.services.embedding import FakeEmbeddingClient, build_embedding_client
from app.services.es import ESClient

SEMANTIC_DOC_ID = "kb-ret-sem"
SEMANTIC_MD = "# 售后政策\n## 退款说明\n订单支付成功后，未发货订单可申请仅退款，款项原路退回。\n"


@pytest.fixture
async def semantic_kb(es_client: ESClient) -> ESClient:
    """用真实 bge-m3 向量索引语义样本；无 key 则整体跳过。"""
    settings = get_settings()
    if not settings.embedding_api_key:
        pytest.skip("未配置 EMBEDDING_API_KEY，跳过真实向量召回用例")
    embedding = build_embedding_client(settings)
    await es_client.delete_by_doc_id(SEMANTIC_DOC_ID)
    parsed = parse_markdown(SEMANTIC_MD, source="退款说明.md", version="1.0")
    await index_chunks(chunk(parsed, doc_id=SEMANTIC_DOC_ID), doc_id=SEMANTIC_DOC_ID,
                       es=es_client, embedding=embedding)
    yield es_client
    await es_client.delete_by_doc_id(SEMANTIC_DOC_ID)


@pytest.mark.spec("SP-RET-002")
@pytest.mark.integration
class TestVectorSearch:
    async def test_ret_201_semantic_recall(self, semantic_kb: ESClient) -> None:
        """"退货" ↔ "退款" 语义近义：向量召回包含"退款"的块。"""
        embedding = build_embedding_client(get_settings())
        hits = await vector_search("退货", semantic_kb, embedding, top_k=5)

        assert hits, "向量检索结果非空"
        assert any("退款" in h["content"] for h in hits[:3]), "近义查询（退货↔退款）应召回"

    async def test_ret_202_dim_consistency(self, kb: ESClient) -> None:
        """向量维度与 embedding 模型一致（dim=1024）：写入与检索均不报错。"""
        settings = get_settings()
        embedding = FakeEmbeddingClient(dim=1024)
        assert settings.embedding_dim == 1024 == embedding.dim  # 配置与客户端一致
        hits = await vector_search("保温杯", kb, embedding, top_k=5)
        assert hits and "score" in hits[0]  # 检索成功即维度校验通过（mapping dims=1024）
