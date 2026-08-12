"""SP-RET-004 重排（硅基流动 bge-reranker-v2-m3 云端 API）：T-RET-401/402（规格）+ 补充。

- T-RET-401 候选数=5：top-20 → top-5，按相关度降序
- T-RET-402 无效输入抛错（空查询 / 空候选 / top_k ≤ 0）
- T-RET-403 未配置 RERANKER_API_KEY → fail fast
- T-RET-404 请求体与响应解析正确（MockTransport，零网络）
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import Settings
from app.retrieval.rerank import (
    RerankUnavailableError,
    SiliconFlowRerankClient,
    build_reranker,
    rerank,
)


class FakeReranker:
    """注入用假重排器：按 relevance_score 降序返回。"""

    def __init__(self, scores: list[float] | None = None) -> None:
        self.scores = scores or [0.9, 0.8, 0.7, 0.6, 0.5]
        self.calls: list[dict] = []

    async def rerank(self, query: str, documents: list[str], top_n: int = 5) -> list[dict]:
        self.calls.append({"query": query, "documents": documents, "top_n": top_n})
        ranked = sorted(
            range(len(documents)),
            key=lambda i: self.scores[i] if i < len(self.scores) else 0.0,
            reverse=True,
        )
        return [{"index": i, "relevance_score": self.scores[i] if i < len(self.scores) else 0.0}
                for i in ranked[:top_n]]


def _docs(n: int = 20) -> list[dict]:
    return [
        {"chunk_id": f"c{i}", "title": "手册", "content": f"文档内容 {i}", "score": 1.0 / (i + 1)}
        for i in range(n)
    ]


@pytest.mark.spec("SP-RET-004")
class TestRerank:
    async def test_ret_401_top5_ordered(self) -> None:
        docs = _docs(20)
        result = await rerank("退货政策", docs, top_k=5, client=FakeReranker())

        assert len(result) == 5  # 候选数=5
        assert [d["chunk_id"] for d in result] == ["c0", "c1", "c2", "c3", "c4"]
        # 与问答 Agent 输入顺序一致：documents 原样透传（按相关度降序）
        assert "content" in result[0] and "score" in result[0]

    async def test_ret_401_client_gets_contents(self) -> None:
        fake = FakeReranker()
        docs = _docs(6)
        await rerank("q", docs, top_k=3, client=fake)
        assert fake.calls[0]["documents"] == [d["content"] for d in docs]
        assert fake.calls[0]["top_n"] == 3

    async def test_ret_402_invalid_inputs(self) -> None:
        with pytest.raises(ValueError, match="查询"):
            await rerank("  ", _docs(3), client=FakeReranker())
        with pytest.raises(ValueError, match="候选"):
            await rerank("q", [], client=FakeReranker())
        with pytest.raises(ValueError, match="top_k"):
            await rerank("q", _docs(3), top_k=0, client=FakeReranker())

    def test_ret_403_missing_api_key(self) -> None:
        settings = Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m")
        with pytest.raises(RerankUnavailableError, match="RERANKER_API_KEY"):
            build_reranker(settings)

    async def test_ret_404_request_and_response(self) -> None:
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/rerank"):  # base_url 含 /v1 前缀
                captured["body"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "id": "r1",
                        "model": "bge-reranker-v2-m3",
                        "results": [
                            {"index": 2, "relevance_score": 0.95},
                            {"index": 0, "relevance_score": 0.80},
                            {"index": 1, "relevance_score": 0.60},
                        ],
                    },
                )
            return httpx.Response(404)

        client = SiliconFlowRerankClient(
            model="bge-reranker-v2-m3",
            api_key="sf-test",
            base_url="https://api.siliconflow.cn/v1",
            transport=httpx.MockTransport(handler),
        )
        ranked = await client.rerank("退款", ["文档甲", "文档乙", "文档丙"], top_n=3)

        assert captured["body"]["model"] == "bge-reranker-v2-m3"
        assert captured["body"]["query"] == "退款"
        assert captured["body"]["documents"] == ["文档甲", "文档乙", "文档丙"]
        assert captured["body"]["top_n"] == 3
        assert [r["index"] for r in ranked] == [2, 0, 1]  # 按相关度降序

    async def test_ret_404_http_error_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        client = SiliconFlowRerankClient(
            model="bge-reranker-v2-m3",
            api_key="sf-test",
            base_url="https://api.siliconflow.cn/v1",
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(httpx.HTTPError):
            await client.rerank("q", ["d"], top_n=1)
