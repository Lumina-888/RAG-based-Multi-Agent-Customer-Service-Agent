"""Embedding 云端 API 封装（硅基流动 bge-m3，dim=1024，SP-ING-003 前置）。

- T-EMB-101 向量维度与配置一致（dim=1024，对齐 SP-RET-002）
- T-EMB-102 FakeEmbedding 注入生效，调用历史可断言（同 SP-CFG-004 模式）
- T-EMB-103 服务端返回维度与配置不一致 → 抛 EmbeddingError（防静默错配）
- T-EMB-104 上游 HTTP 错误上抛（由调用方映射错误码）
"""
from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.services.embedding import EmbeddingError, FakeEmbeddingClient, OpenAIEmbeddingClient


def _settings() -> Settings:
    return Settings(_env_file=None, deepseek_api_key="dk", mimo_api_key="mk")


def _mock_transport(payload: dict) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


@pytest.mark.spec("SP-ING-003")
class TestEmbedding:
    async def test_emb_101_dimension_matches_config(self) -> None:
        """批量 embed 返回维度与配置一致（1024）。"""
        fake = FakeEmbeddingClient(dim=1024)
        vectors = await fake.embed(["手机", "退款政策"])
        assert len(vectors) == 2
        assert all(len(v) == 1024 for v in vectors)
        # 同一文本两次调用结果确定性一致（便于评测复现）
        again = await fake.embed(["手机"])
        assert again[0] == vectors[0]

    async def test_emb_102_fake_injection(self) -> None:
        """FakeEmbedding 注入生效：零网络请求，调用历史可断言。"""
        fake = FakeEmbeddingClient(dim=8)
        vectors = await fake.embed(["ping", "pong"])
        assert fake.calls[0]["texts"] == ["ping", "pong"]
        assert len(vectors) == 2
        assert all(len(v) == 8 for v in vectors)

    async def test_emb_103_dim_mismatch_raises(self) -> None:
        """服务端返回维度与配置不一致 → EmbeddingError（防静默错配）。"""
        client = OpenAIEmbeddingClient(
            "bge-m3",
            "sk-test",
            "https://api.example.com/v1",
            dim=1024,
            transport=_mock_transport({"data": [{"index": 0, "embedding": [0.1, 0.2]}]}),
        )
        with pytest.raises(EmbeddingError):
            await client.embed(["x"])

    async def test_emb_104_http_error_propagates(self) -> None:
        """上游 5xx 上抛 httpx 异常（调用方负责错误码映射）。"""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        client = OpenAIEmbeddingClient(
            "bge-m3",
            "sk-test",
            "https://api.example.com/v1",
            dim=1024,
            transport=httpx.MockTransport(handler),
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.embed(["x"])

    async def test_emb_105_embedding_config_defaults(self) -> None:
        """配置默认值：bge-m3 + 硅基流动 base_url + 1024 维。"""
        s = _settings()
        assert s.embedding_model == "bge-m3"
        assert s.embedding_base_url == "https://api.siliconflow.cn/v1"
        assert s.embedding_dim == 1024
