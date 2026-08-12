"""SP-ING-004 知识库管理 API（离线单元层）：Fake 依赖注入，零 ES / 零网络。

- T-ING-411 上传 .md → 后台 解析→分块→索引 完成（表格小节落库）
- T-ING-412 非法扩展名 → 4001 统一 JSON
- T-ING-413 /kb/search 调试检索返回原始结果
"""
from __future__ import annotations

import time

import pytest
from fastapi import FastAPI

from app.api import kb
from app.services.embedding import FakeEmbeddingClient


class FakeES:
    """最小内存 ES：覆盖 ESWriter + search_match（见 app/services/es.py 协议）。"""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    async def ensure_kb_index(self, dim: int = 1024) -> None:
        pass

    async def delete_by_doc_id(self, doc_id: str) -> None:
        self.docs = {k: v for k, v in self.docs.items() if v["doc_id"] != doc_id}

    async def bulk_index(self, docs: list[dict]) -> int:
        for d in docs:
            self.docs[d["_id"]] = {k: v for k, v in d.items() if k != "_id"}
        return len(docs)

    async def count_doc(self, doc_id: str) -> int:
        return sum(1 for v in self.docs.values() if v["doc_id"] == doc_id)

    async def search_match(self, q: str, size: int = 10) -> list[dict]:
        return [
            {
                "chunk_id": _id,
                "doc_id": v["doc_id"],
                "title": v["title"],
                "heading_path": v["heading_path"],
                "content": v["content"],
                "score": 1.0 if q in v["content"] else 0.1,
            }
            for _id, v in self.docs.items()
            if q in v["content"]
        ][:size]


MD = """# 商品常见问题
Q: 如何申请退货？
A: 在订单详情页点击申请售后即可。

## 退款时限
| 场景 | 时限 |
|---|---|
| 未发货 | 随时 |
退款将在 3~5 个工作日内原路退回。
"""


@pytest.fixture
def kb_app() -> tuple[FastAPI, kb.IngestionDeps]:
    """最小 FastAPI 应用（只挂 kb 路由）+ Fake 依赖：不导入 app.main，避免
    触发 setup_logging 破坏 M0 日志单测。"""
    app = FastAPI()
    app.include_router(kb.router)
    deps = kb.IngestionDeps(
        es=FakeES(), embedding=FakeEmbeddingClient(dim=1024), mineru=None, llm=None
    )
    app.dependency_overrides[kb.get_ingestion_deps] = lambda: deps
    return app, deps


def _client(app: FastAPI):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.mark.spec("SP-ING-004")
class TestKbApiOffline:
    async def test_ing_411_upload_indexes_pipeline(self, kb_app: tuple[FastAPI, kb.IngestionDeps]) -> None:
        app, deps = kb_app
        resp = _client(app).post(
            "/api/v1/kb/documents",
            files={"file": ("商品FAQ.md", MD.encode("utf-8"), "text/markdown")},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        doc_id = body["data"]["doc_id"]
        assert body["data"]["status"] == "processing"

        # 后台任务：解析→分块→索引（轮询兜底 TestClient 行为差异）
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and await deps.es.count_doc(doc_id) == 0:
            time.sleep(0.05)
        assert await deps.es.count_doc(doc_id) >= 2  # FAQ 小节 + 表格小节
        assert any("| 场景 | 时限 |" in v["content"] for v in deps.es.docs.values())

    def test_ing_412_unsupported_extension_4001(self, kb_app: tuple[FastAPI, kb.IngestionDeps]) -> None:
        app, _ = kb_app
        resp = _client(app).post(
            "/api/v1/kb/documents",
            files={"file": ("说明.txt", b"plain", "text/plain")},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == 4001
        assert body["data"] is None

    def test_ing_413_search_returns_hits(self, kb_app: tuple[FastAPI, kb.IngestionDeps]) -> None:
        app, _ = kb_app
        client = _client(app)
        client.post(
            "/api/v1/kb/documents",
            files={"file": ("商品FAQ.md", MD.encode("utf-8"), "text/markdown")},
        )
        resp = client.get("/api/v1/kb/search", params={"q": "退款"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["count"] >= 1
        hit = body["data"]["hits"][0]
        assert {"chunk_id", "doc_id", "title", "heading_path", "content", "score"} <= set(hit)
