"""H 真实 API 联调冒烟脚本（scripts/api_smoke.py）单测：MockTransport 注入，零网络。

- T-API-101 占位符/缺 key → SKIPPED（不发起任何请求）
- T-API-102 LLM 冒烟：200 回复 → OK；401 → FAILED（Key 无效提示）
- T-API-103 embedding：维度与配置一致 → OK；不一致 → FAILED
- T-API-104 rerank：语义排序正确 → OK；排序异常 → FAILED
- T-API-105 mineru：任意 HTTP 响应 → OK（连通性）；连接失败 → FAILED
- T-API-106 vision：缺 DEMO_IMAGE_URL → SKIPPED；配置齐全 + 回复 → OK
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from api_smoke import (  # noqa: E402
    check_chat,
    check_embedding,
    check_mineru,
    check_rerank,
    check_vision,
)
from app.core.config import Settings  # noqa: E402

REAL_KEYS = dict(
    deepseek_api_key="sk-test-deepseek-1234567890",
    mimo_api_key="sk-test-mimo-1234567890",
    embedding_api_key="sk-test-embed-1234567890",
    reranker_api_key="sk-test-rerank-1234567890",
    mineru_api_key="sk-test-mineru-1234567890",
)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**REAL_KEYS, **overrides})


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _openai_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


class TestApiSmoke:
    async def test_api_101_placeholder_keys_skipped(self) -> None:
        cfg = Settings(
            _env_file=None,
            deepseek_api_key="your_deepseek_api_key_here",
            mimo_api_key="your_mimo_api_key_here",
            embedding_api_key="your_siliconflow_api_key_here",
            reranker_api_key="your_siliconflow_api_key_here",
            mineru_api_key="your_mineru_api_key_here",
        )

        async def _boom(request):
            raise AssertionError("占位符不应发起请求")

        transport = _transport(_boom)
        results = [
            await check_chat("deepseek_chat", cfg.model_main, cfg.deepseek_api_key, cfg.deepseek_base_url, transport),
            await check_embedding(cfg, transport),
            await check_rerank(cfg, transport),
            await check_mineru(cfg, transport),
            await check_vision(cfg, transport),
        ]
        assert all(r.status == "SKIPPED" for r in results)

    async def test_api_102_chat_ok_and_401(self) -> None:
        cfg = _settings()
        ok = await check_chat(
            "deepseek_chat", cfg.model_main, cfg.deepseek_api_key, cfg.deepseek_base_url,
            _transport(lambda request: _openai_response("联调OK")),
        )
        assert ok.status == "OK" and "联调OK" in ok.detail

        auth_fail = await check_chat(
            "deepseek_chat", cfg.model_main, cfg.deepseek_api_key, cfg.deepseek_base_url,
            _transport(lambda request: httpx.Response(401, json={"error": "invalid key"})),
        )
        assert auth_fail.status == "FAILED" and "401" in auth_fail.detail

    async def test_api_103_embedding_dim_check(self) -> None:
        cfg = _settings()
        ok = await check_embedding(
            cfg, _transport(lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * cfg.embedding_dim}]})),
        )
        assert ok.status == "OK" and f"dim={cfg.embedding_dim}" in ok.detail

        mismatch = await check_embedding(
            cfg, _transport(lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 3}]})),
        )
        assert mismatch.status == "FAILED" and "维度" in mismatch.detail

    async def test_api_104_rerank_order_check(self) -> None:
        cfg = _settings()
        good = await check_rerank(
            cfg, _transport(lambda request: httpx.Response(200, json={"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]})),
        )
        assert good.status == "OK" and "排序正确" in good.detail

        bad = await check_rerank(
            cfg, _transport(lambda request: httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}, {"index": 1, "relevance_score": 0.1}]})),
        )
        assert bad.status == "FAILED" and "排序异常" in bad.detail

    async def test_api_105_mineru_connectivity(self, monkeypatch) -> None:
        cfg = _settings()
        reachable = await check_mineru(
            cfg, _transport(lambda request: httpx.Response(404, json={"detail": "not found"})),
        )
        assert reachable.status == "OK"  # 任意 HTTP 响应即可达

        def _conn_error(request):
            raise httpx.ConnectError("connection refused", request=request)

        down = await check_mineru(cfg, _transport(_conn_error))
        assert down.status == "FAILED"

    async def test_api_106_vision_guard_and_ok(self, monkeypatch) -> None:
        monkeypatch.delenv("DEMO_IMAGE_URL", raising=False)
        cfg = _settings()
        skipped = await check_vision(cfg, _transport(lambda request: httpx.Response(200, json={})))
        assert skipped.status == "SKIPPED" and "DEMO_IMAGE_URL" in skipped.detail

        monkeypatch.setenv("DEMO_IMAGE_URL", "https://example.com/demo.png")
        ok = await check_vision(
            cfg, _transport(lambda request: _openai_response("一张商品图片")),
        )
        assert ok.status == "OK" and "商品图片" in ok.detail
