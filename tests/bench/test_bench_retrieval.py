"""SP-RET-006 检索性能（T-RET-601）：基准测试冒烟（需 ES，否则 skip）。

完整基准脚本：`tests/bench/bench_retrieval.py`（可独立运行）。
"""
from __future__ import annotations

import pytest

from app.services.embedding import FakeEmbeddingClient

from .bench_retrieval import run_bench


@pytest.mark.spec("SP-RET-006")
@pytest.mark.integration
class TestRetrievalBench:
    async def test_ret_601_p95_under_500ms(self, kb) -> None:
        """本地 ES 单查询 P95 < 500ms（含融合，不含重排）。"""
        stats = await run_bench(
            kb, FakeEmbeddingClient(dim=1024), ["退货政策", "退款要多久", "保温杯 保温时长"], top_k=10
        )

        assert stats["count"] == 3
        assert stats["p95_ms"] < 500, f"P95={stats['p95_ms']}ms 超阈（SP-RET-006）"
