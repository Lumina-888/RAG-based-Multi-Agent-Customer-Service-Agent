"""SP-RET-006 检索性能基准（T-RET-601）：本地 ES 单查询 P95 < 500ms（含融合，不含重排）。

用法（需本地 ES + 已索引知识库）：
    python tests/bench/bench_retrieval.py [--queries N] [--top_k K]

说明：
- 指标：hybrid_search（默认 RRF 融合）单查询延迟 P95 / P50 / max
- 数据准备：先通过 `/api/v1/kb/documents` 上传 data/raw_docs 下的文档
- 重排 P95 < 800ms（硅基流动 bge-reranker-v2-m3 API）不在本脚本内联测，
  性能不达标不作为验收阻塞（SP-RET-006 豁免口径）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

from app.core.config import get_settings
from app.retrieval.hybrid_search import hybrid_search
from app.services.embedding import build_embedding_client
from app.services.es import ESClient

#: 覆盖 实体/关键词/语义 三类查询形态
SAMPLE_QUERIES = [
    "退货政策", "退款要多久", "订单怎么还没发货", "保温杯 保温时长",
    "发票怎么开", "商品为什么这么贵", "未发货订单能退款吗", "7 天无理由退货",
    "换货流程", "质保期多久", "运费谁承担", "如何申请售后",
]


async def run_bench(es: ESClient, embedding, queries: list[str], top_k: int = 10) -> dict:
    """对给定查询列表执行混合检索，返回延迟统计。"""
    latencies_ms: list[float] = []
    strategies: set[str] = set()
    for q in queries:
        t0 = time.perf_counter()
        result = await hybrid_search(q, es, embedding=embedding, strategy="rrf", top_k=top_k)
        latencies_ms.append((time.perf_counter() - t0) * 1000)
        strategies.add(result["strategy"])
    latencies_ms.sort()
    n = len(latencies_ms)
    return {
        "count": n,
        "p50_ms": round(latencies_ms[n // 2], 2),
        "p95_ms": round(latencies_ms[max(int(n * 0.95) - 1, 0)], 2),
        "max_ms": round(latencies_ms[-1], 2),
        "mean_ms": round(statistics.mean(latencies_ms), 2),
        "strategies": sorted(strategies),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="SP-RET-006 检索性能基准")
    parser.add_argument("--queries", type=int, default=len(SAMPLE_QUERIES))
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    settings = get_settings()
    es = ESClient(settings.es_host, timeout=30.0)
    if not await es.ping():
        print(json.dumps({"error": "ES 不可用（需本地 ES 8.x）"}, ensure_ascii=False))
        return 2
    embedding = build_embedding_client(settings)
    stats = await run_bench(es, embedding, SAMPLE_QUERIES[: args.queries], top_k=args.top_k)
    stats["threshold_p95_ms"] = 500  # SP-RET-006：单查询 P95 < 500ms
    stats["pass"] = stats["p95_ms"] < 500
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    await es.aclose()
    return 0 if stats["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
