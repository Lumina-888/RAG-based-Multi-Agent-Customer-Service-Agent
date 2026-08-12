"""ES 客户端（httpx 直连）单元测试：mapping / bulk ndjson / 计数 / 检索 / 清理。

- T-ING-307 ensure_kb_index：PUT mapping（dense_vector dims 与配置一致），已存在幂等
- T-ING-308 bulk_index：NDJSON 格式正确、refresh=wait_for、成功计数不含错误条目
- T-ING-309 delete_by_doc_id / count_doc / search_match / ping
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.services.es import ESClient


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, bytes | None]] = []  # (method, path, params, body)
        self.bulk_items = [
            {"index": {"_id": "d-0", "status": 201, "result": "created"}},
            {"index": {"_id": "d-1", "status": 200, "result": "updated"}},
            {"index": {"_id": "d-2", "status": 500, "error": {"type": "mapper_parsing_exception"}}},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            (request.method, request.url.path, dict(request.url.params), request.content)
        )
        if request.url.path == "/":
            return httpx.Response(200, json={"version": {"number": "8.15.0"}})
        if request.url.path == "/kb_chunks" and request.method == "PUT":
            return httpx.Response(200, json={"acknowledged": True})
        if request.url.path == "/_bulk":
            return httpx.Response(200, json={"items": self.bulk_items, "errors": True})
        if request.url.path == "/kb_chunks/_count":
            return httpx.Response(200, json={"count": 5})
        if request.url.path == "/kb_chunks/_search":
            return httpx.Response(
                200,
                json={
                    "hits": {
                        "hits": [
                            {
                                "_id": "d-0",
                                "_score": 2.5,
                                "_source": {
                                    "doc_id": "doc",
                                    "title": "售后政策",
                                    "heading_path": "售后政策 / 退货规则",
                                    "content": "退货规则内容",
                                },
                            }
                        ]
                    }
                },
            )
        if request.url.path == "/kb_chunks/_delete_by_query":
            return httpx.Response(200, json={"deleted": 3})
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def rec() -> _Recorder:
    return _Recorder()


@pytest.fixture
def client(rec: _Recorder) -> ESClient:
    return ESClient("http://es:9200", timeout=5, transport=httpx.MockTransport(rec.handler))


@pytest.mark.spec("SP-ING-003")
class TestESClient:
    async def test_ing_307_ensure_kb_index_mapping(self, client: ESClient, rec: _Recorder) -> None:
        await client.ensure_kb_index(dim=1024)

        method, path, params, body = rec.calls[0]
        assert (method, path) == ("PUT", "/kb_chunks")
        mapping = json.loads(body)
        props = mapping["mappings"]["properties"]
        assert props["content"]["type"] == "text"
        assert props["title"]["type"] == "text"
        assert props["doc_id"]["type"] == "keyword"
        assert props["seq"]["type"] == "integer"
        assert props["embedding_ver"]["type"] == "keyword"
        assert props["embedding"] == {
            "type": "dense_vector", "dims": 1024, "index": True, "similarity": "cosine",
        }

    async def test_ing_307_ensure_kb_index_idempotent(self, rec: _Recorder) -> None:
        already_exists = httpx.Response(
            400, json={"error": {"type": "resource_already_exists_exception"}}
        )
        rec.handler = lambda req: already_exists  # noqa: E731 - 幂等：已存在不报错
        client = ESClient("http://es:9200", transport=httpx.MockTransport(rec.handler))
        await client.ensure_kb_index()  # 不应抛错

    async def test_ing_308_bulk_ndjson_format(self, client: ESClient, rec: _Recorder) -> None:
        n = await client.bulk_index(
            [
                {"_id": "d-0", "content": "甲", "seq": 0},
                {"_id": "d-1", "content": "乙", "seq": 1},
                {"_id": "d-2", "content": "丙", "seq": 2},
            ]
        )

        assert n == 2  # 成功计数不含 error 条目
        method, path, params, body = next(c for c in rec.calls if c[1] == "/_bulk")
        assert method == "POST"
        assert params == {"refresh": "wait_for"}  # 写入后可立即检索
        lines = body.decode().splitlines()
        assert len(lines) == 6  # 3 条 action + 3 条 doc
        assert json.loads(lines[0]) == {"index": {"_index": "kb_chunks", "_id": "d-0"}}
        assert json.loads(lines[1]) == {"content": "甲", "seq": 0}
        assert json.loads(lines[4])["index"]["_id"] == "d-2"

    async def test_ing_308_bulk_empty_noop(self, client: ESClient, rec: _Recorder) -> None:
        assert await client.bulk_index([]) == 0
        assert rec.calls == []

    async def test_ing_309_count_doc(self, client: ESClient, rec: _Recorder) -> None:
        count = await client.count_doc("doc")
        assert count == 5
        method, path, params, body = rec.calls[0]
        assert json.loads(body)["query"] == {"term": {"doc_id": "doc"}}

    async def test_ing_309_search_match_fields(self, client: ESClient, rec: _Recorder) -> None:
        hits = await client.search_match("退货", size=10)
        assert len(hits) == 1
        hit = hits[0]
        assert hit["chunk_id"] == "d-0"
        assert hit["title"] == "售后政策"
        assert hit["content"] == "退货规则内容"
        assert hit["heading_path"] == "售后政策 / 退货规则"
        assert hit["score"] == 2.5
        # 标题字段权重为内容 2 倍（SP-RET-001 口径）
        method, path, params, body = rec.calls[0]
        query = json.loads(body)["query"]
        assert query["multi_match"]["fields"] == ["title^2", "content"]

    async def test_ing_309_delete_by_doc_id(self, client: ESClient, rec: _Recorder) -> None:
        await client.delete_by_doc_id("doc")
        method, path, params, body = rec.calls[0]
        assert path == "/kb_chunks/_delete_by_query"
        assert params == {"refresh": "wait_for"}
        assert json.loads(body)["query"] == {"term": {"doc_id": "doc"}}

    async def test_ing_309_ping(self, client: ESClient, rec: _Recorder) -> None:
        assert await client.ping() is True

    # ---------- M2 检索路径（SP-RET-001/002/005） ----------

    async def test_ing_310_search_knn_request(self, client: ESClient, rec: _Recorder) -> None:
        hits = await client.search_knn([0.1] * 1024, size=5, num_candidates=100)

        assert hits[0]["chunk_id"] == "d-0"
        method, path, params, body = rec.calls[0]
        assert method == "POST" and path == "/kb_chunks/_search"
        payload = json.loads(body)
        assert payload["knn"] == {
            "field": "embedding",
            "query_vector": [0.1] * 1024,
            "k": 5,
            "num_candidates": 100,
        }
        assert "embedding" not in payload["_source"]  # 不回传向量

    async def test_ing_311_search_rrf_request(self, client: ESClient, rec: _Recorder) -> None:
        hits = await client.search_rrf("退货", [0.2] * 1024, size=10, k=60)

        assert hits[0]["title"] == "售后政策"
        method, path, params, body = rec.calls[0]
        payload = json.loads(body)
        rrf = payload["query"]["rank"]["rrf"]
        assert rrf["rank_constant"] == 60  # 与 fusion.rrf_fuse 的 k 对标
        queries = rrf["queries"]
        assert queries[0]["multi_match"]["fields"] == ["title^2", "content"]
        assert queries[1]["knn"]["field"] == "embedding"
