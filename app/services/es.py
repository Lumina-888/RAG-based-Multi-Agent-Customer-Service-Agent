"""ES REST 客户端（httpx 直连，不引入官方 SDK）：M1 索引写入 / M2 检索前置。

- `kb_chunks` 索引 mapping：content/title(text, BM25) + embedding(dense_vector) +
  元数据字段（doc_id/source/heading_path/seq/embedding_ver）
- 幂等由确定性 `_id=doc_id-seq` 保证（SP-ING-003）
- 支持注入 `httpx.MockTransport`，单测零真实网络
"""
from __future__ import annotations

import json

import httpx


class ESClient:
    """最小 ES 8.x 客户端：建索引 / bulk / 按 doc_id 清理 / 计数 / 调试检索。"""

    KB_INDEX = "kb_chunks"

    def __init__(
        self,
        host: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=host.rstrip("/"), timeout=timeout, transport=transport
        )

    async def ping(self) -> bool:
        """探测 ES 可用性（集成测试守卫）。"""
        try:
            resp = await self._http.get("/")
            return resp.status_code < 500
        except httpx.HTTPError:
            return False

    async def ensure_kb_index(self, dim: int = 1024) -> None:
        """幂等建索引：mapping 与 SP-ING-003 / 设计文档 §3.4 对齐。"""
        mapping = {
            "mappings": {
                "properties": {
                    "title": {"type": "text"},
                    "content": {"type": "text"},
                    "heading_path": {"type": "text"},
                    "doc_id": {"type": "keyword"},
                    "source": {"type": "keyword"},
                    "seq": {"type": "integer"},
                    "embedding_ver": {"type": "keyword"},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": dim,
                        "index": True,
                        "similarity": "cosine",
                    },
                }
            }
        }
        resp = await self._http.put(f"/{self.KB_INDEX}", json=mapping)
        if resp.status_code == 400 and "resource_already_exists_exception" in resp.text:
            return  # 已存在 → 幂等
        resp.raise_for_status()

    async def delete_by_doc_id(self, doc_id: str) -> None:
        """重索引前清理该 doc_id 全部残留块（含文档缩小后的多余 seq）。"""
        resp = await self._http.post(
            f"/{self.KB_INDEX}/_delete_by_query?refresh=true",
            json={"query": {"term": {"doc_id": doc_id}}},
        )
        resp.raise_for_status()

    async def bulk_index(self, docs: list[dict]) -> int:
        """NDJSON bulk 写入（`_id` 确定性覆盖），返回成功条数。"""
        if not docs:
            return 0
        lines: list[str] = []
        for d in docs:
            lines.append(
                json.dumps({"index": {"_index": self.KB_INDEX, "_id": d["_id"]}}, ensure_ascii=False)
            )
            lines.append(
                json.dumps({k: v for k, v in d.items() if k != "_id"}, ensure_ascii=False)
            )
        resp = await self._http.post(
            "/_bulk?refresh=wait_for",
            content="\n".join(lines) + "\n",
            headers={"content-type": "application/x-ndjson"},
        )
        resp.raise_for_status()
        items = resp.json()["items"]
        return sum(1 for it in items if "error" not in it.get("index", {}))

    async def count_doc(self, doc_id: str) -> int:
        resp = await self._http.post(
            f"/{self.KB_INDEX}/_count", json={"query": {"term": {"doc_id": doc_id}}}
        )
        resp.raise_for_status()
        return int(resp.json()["count"])

    async def count(self) -> int:
        resp = await self._http.get(f"/{self.KB_INDEX}/_count")
        resp.raise_for_status()
        return int(resp.json()["count"])

    #: 检索返回字段（不含 embedding 向量，避免回传 1024 维数据）
    _SOURCE_FIELDS = ["doc_id", "title", "heading_path", "content", "seq", "source"]

    def _map_hits(self, resp: httpx.Response) -> list[dict]:
        return [
            {
                "chunk_id": h["_id"],
                "doc_id": h["_source"].get("doc_id"),
                "title": h["_source"].get("title"),
                "heading_path": h["_source"].get("heading_path"),
                "content": h["_source"].get("content"),
                "score": h.get("_score"),
            }
            for h in resp.json()["hits"]["hits"]
        ]

    async def search_match(self, q: str, size: int = 10) -> list[dict]:
        """BM25 检索（标题权重为内容 2 倍，SP-RET-001 口径）；`/kb/search` 亦复用。"""
        resp = await self._http.post(
            f"/{self.KB_INDEX}/_search",
            json={
                "size": size,
                "_source": self._SOURCE_FIELDS,
                "query": {"multi_match": {"query": q, "fields": ["title^2", "content"]}},
            },
        )
        resp.raise_for_status()
        return self._map_hits(resp)

    async def search_knn(
        self, q_vector: list[float], size: int = 10, num_candidates: int = 200
    ) -> list[dict]:
        """向量检索（bge-m3，SP-RET-002）：kNN 按余弦相似度降序。"""
        resp = await self._http.post(
            f"/{self.KB_INDEX}/_search",
            json={
                "size": size,
                "_source": self._SOURCE_FIELDS,
                "knn": {
                    "field": "embedding",
                    "query_vector": q_vector,
                    "k": size,
                    "num_candidates": num_candidates,
                },
            },
        )
        resp.raise_for_status()
        return self._map_hits(resp)

    async def search_rrf(
        self,
        q: str,
        q_vector: list[float],
        size: int = 10,
        k: int = 60,
        num_candidates: int = 200,
    ) -> list[dict]:
        """ES 原生 RRF 融合（SP-RET-005，需 ES ≥ 8.8）：BM25 + kNN 双路，
        `rank_constant=k` 与 `fusion.rrf_fuse` 行为对标。"""
        resp = await self._http.post(
            f"/{self.KB_INDEX}/_search",
            json={
                "size": size,
                "_source": self._SOURCE_FIELDS,
                "rank": {
                    "rrf": {
                        "rank_constant": k,
                        "window_size": 100,
                        "queries": [
                            {"multi_match": {"query": q, "fields": ["title^2", "content"]}},
                            {
                                "knn": {
                                    "field": "embedding",
                                    "query_vector": q_vector,
                                    "k": size,
                                    "num_candidates": num_candidates,
                                }
                            },
                        ],
                    }
                },
            },
        )
        resp.raise_for_status()
        return self._map_hits(resp)

    async def aclose(self) -> None:
        await self._http.aclose()
