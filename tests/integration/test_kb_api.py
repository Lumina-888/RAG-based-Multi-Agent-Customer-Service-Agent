"""SP-ING-004 知识库管理 API（需真实 ES）：T-ING-401 ~ 403。

- T-ING-401 上传文档 → 后台解析→分块→索引完成（返回 doc_id 与状态）
- T-ING-402 `/kb/search` 调试检索返回原始结果
- T-ING-403 非法扩展名 → 4001 统一 JSON（非后台任务）
"""
from __future__ import annotations

import time

import pytest

from app.api import kb
from app.services.embedding import FakeEmbeddingClient
from app.services.es import ESClient

# 注意：app.main 不在模块级导入（其 setup_logging 副作用会破坏 M0 日志单测）

MD = """# 商品常见问题
Q: 如何申请退货？
A: 在订单详情页点击申请售后，选择退货退款即可。

## 退款时限
| 场景 | 时限 |
|---|---|
| 未发货 | 随时 |
| 已签收 | 7 天 |
退款将在 3~5 个工作日内原路退回。
"""


@pytest.fixture
def kb_deps(es_client: ESClient) -> kb.IngestionDeps:
    from app.main import app  # 延迟导入：避免收集期触发 setup_logging

    deps = kb.IngestionDeps(
        es=es_client, embedding=FakeEmbeddingClient(dim=1024), mineru=None, llm=None
    )
    app.dependency_overrides[kb.get_ingestion_deps] = lambda: deps
    yield deps
    app.dependency_overrides.clear()


def _wait_indexed(es: ESClient, doc_id: str, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        n = es.count_doc(doc_id)
        if n > 0:
            return n
        time.sleep(0.2)
    return 0


@pytest.mark.spec("SP-ING-004")
@pytest.mark.integration
class TestKbApi:
    def test_ing_401_upload_then_indexed(self, kb_deps: kb.IngestionDeps) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        resp = client.post(
            "/api/v1/kb/documents",
            files={"file": ("商品FAQ.md", MD.encode("utf-8"), "text/markdown")},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "processing"
        doc_id = body["data"]["doc_id"]
        assert doc_id

        # 后台任务完成 → 分块已落库（含表格小节）
        assert _wait_indexed(kb_deps.es, doc_id) >= 2

    def test_ing_402_search_returns_hits(self, kb_deps: kb.IngestionDeps) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        client.post(
            "/api/v1/kb/documents",
            files={"file": ("商品FAQ.md", MD.encode("utf-8"), "text/markdown")},
        )
        resp = client.get("/api/v1/kb/search", params={"q": "退货"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["count"] >= 1  # 检索命中
        hit = body["data"]["hits"][0]
        assert "title" in hit and "content" in hit and "score" in hit
        assert "退货" in hit["content"] or "退货" in hit["title"]

    def test_ing_403_unsupported_extension_4001(self, kb_deps: kb.IngestionDeps) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        resp = client.post(
            "/api/v1/kb/documents",
            files={"file": ("说明.txt", b"plain text", "text/plain")},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 4001  # 统一错误码（SP-API-GEN）
        assert body["data"] is None
