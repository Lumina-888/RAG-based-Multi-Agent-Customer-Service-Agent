"""SP-CHAT-003 首响性能基准（T-RET-301 并发压测）：直连 app:8000（绕过 Nginx 限流）。

用法（需完整服务：postgres/redis/es + LLM keys，先 `uvicorn app.main:app --port 8000`）：
    python tests/bench/bench_chat.py [--concurrency 20] [--rounds 5] [--base-url http://localhost:8000]

指标（SP-CHAT-003）：
- 首条 SSE 事件（intent）延迟 P95 < 2s
- 完整回复（done）P95 < 15s
- 20 并发不报错（error_rate = 0）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid

import httpx


async def _one(client: httpx.AsyncClient, base_url: str, tag: str) -> dict:
    payload = {
        "session_id": f"bench-{tag}-{uuid.uuid4().hex[:8]}",
        "message": "保温杯多少钱，什么时候发货",
    }
    t0 = time.perf_counter()
    try:
        async with client.stream("POST", f"{base_url}/api/v1/chat", json=payload) as resp:
            first_event_ms: float | None = None
            done_seen = False
            async for line in resp.aiter_lines():
                if first_event_ms is None and line.startswith("data:"):
                    first_event_ms = (time.perf_counter() - t0) * 1000  # 首条事件（intent）
                if line.startswith("event: done"):
                    done_seen = True
            return {
                "status": resp.status_code,
                "first_event_ms": first_event_ms,
                "total_ms": (time.perf_counter() - t0) * 1000,
                "done_seen": done_seen,
            }
    except Exception as exc:  # noqa: BLE001
        return {"status": 0, "first_event_ms": None, "total_ms": None, "error": str(exc)}


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(int(len(ordered) * 0.95) - 1, 0)]


async def run_bench(base_url: str, concurrency: int = 20, rounds: int = 5) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        tasks = [_one(client, base_url, f"r{r}") for r in range(rounds) for _ in range(concurrency)]
        results = await asyncio.gather(*tasks)
    ok = [r for r in results if r.get("status") == 200 and r.get("done_seen")]
    first_events = [r["first_event_ms"] for r in ok if r.get("first_event_ms") is not None]
    totals = [r["total_ms"] for r in ok if r.get("total_ms") is not None]
    return {
        "concurrency": concurrency,
        "rounds": rounds,
        "total_requests": len(results),
        "error_rate": round(1 - len(ok) / len(results), 4),
        "first_event_p95_ms": round(_p95(first_events), 2),
        "first_event_p50_ms": round(statistics.median(first_events), 2) if first_events else None,
        "total_p95_ms": round(_p95(totals), 2),
        "thresholds": {"first_event_p95_ms": 2000, "total_p95_ms": 15000, "error_rate": 0.0},
        "pass": _p95(first_events) < 2000 and _p95(totals) < 15000 and (1 - len(ok) / len(results)) == 0,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description="SP-CHAT-003 对话首响并发压测（直连 app:8000）")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    stats = await run_bench(args.base_url, args.concurrency, args.rounds)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if stats["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
