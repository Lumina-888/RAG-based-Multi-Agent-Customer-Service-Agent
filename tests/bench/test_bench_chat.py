"""SP-CHAT-003 首响性能（T-CHAT-301）：并发压测冒烟（需 app:8000 在线，否则 skip）。

完整基准脚本：`tests/bench/bench_chat.py`（可独立运行）。
"""
from __future__ import annotations

import httpx
import pytest

from .bench_chat import run_bench


@pytest.mark.spec("SP-CHAT-003")
@pytest.mark.integration
class TestChatBench:
    async def test_chat_301_concurrent_no_errors(self) -> None:
        base = "http://localhost:8000"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{base}/api/v1/health")
        except Exception:  # noqa: BLE001
            pytest.skip("app:8000 未在线（需完整服务，见 M9 docker compose）")
        if resp.status_code != 200:
            pytest.skip("app:8000 未在线")

        stats = await run_bench(base, concurrency=5, rounds=2)

        assert stats["error_rate"] == 0  # 并发不报错
        assert stats["first_event_p95_ms"] < 2000  # 首事件 P95 < 2s（SP-CHAT-003）
        assert stats["total_p95_ms"] < 15000  # 完整回复 P95 < 15s
