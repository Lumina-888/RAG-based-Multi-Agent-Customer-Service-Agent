"""H 真实 API 联调冒烟：各外部 API 连通性与错误码核对（M9 部署后上线前检查项）。

逐项探测（缺 key / 占位符 `your_*_key_here` → SKIPPED，不阻塞其余）：
- deepseek_chat  主 LLM 短文本生成（DEEPSEEK_API_KEY）
- mimo_chat      备 LLM 降级链路（MIMO_API_KEY）
- embedding      bge-m3 向量维度核对（EMBEDDING_API_KEY，期望 dim=1024）
- rerank         bge-reranker-v2-m3 语义排序核对（RERANKER_API_KEY）
- mineru         MinerU 云端连通性（MINERU_API_KEY；任意 HTTP 响应即可达）
- vision         图片理解（MIMO_API_KEY + DEMO_IMAGE_URL，默认跳过）

用法：python scripts/api_smoke.py [--json]
退出码：存在 FAILED → 1；全部 OK/SKIPPED → 0
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import Settings, get_settings  # noqa: E402
from app.ingestion.parser import MinerUClient  # noqa: E402
from app.retrieval.rerank import SiliconFlowRerankClient  # noqa: E402
from app.services.embedding import OpenAIEmbeddingClient  # noqa: E402
from app.services.llm import OpenAIClient  # noqa: E402

CHECK_PROMPT = "你好，请只回复四个字：联调OK"


@dataclass
class CheckResult:
    name: str
    status: str  # OK / SKIPPED / FAILED
    detail: str = ""


def _has_key(key: str) -> bool:
    """真实 key 判定：非空、非占位符、长度足够。"""
    return bool(key) and "your_" not in key and len(key) > 8


def _http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        hint = "Key 无效或过期" if code == 401 else "服务端错误"
        return f"HTTP {code} {hint}"
    return f"{type(exc).__name__}: {exc}"


async def check_chat(
    name: str, model: str, api_key: str, base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> CheckResult:
    if not _has_key(api_key):
        return CheckResult(name, "SKIPPED", "未配置 API Key")
    try:
        client = OpenAIClient(model, api_key, base_url, timeout=15.0, transport=transport)
        reply = await client.chat([{"role": "user", "content": CHECK_PROMPT}])
        if not reply.strip():
            return CheckResult(name, "FAILED", "返回内容为空")
        return CheckResult(name, "OK", f"回复: {reply.strip()[:40]!r}")
    except Exception as exc:  # noqa: BLE001 - 冒烟统一兜底
        return CheckResult(name, "FAILED", _http_error(exc))


async def check_embedding(
    config: Settings, transport: httpx.AsyncBaseTransport | None = None,
) -> CheckResult:
    if not _has_key(config.embedding_api_key):
        return CheckResult("embedding", "SKIPPED", "未配置 EMBEDDING_API_KEY")
    try:
        client = OpenAIEmbeddingClient(
            config.embedding_model, config.embedding_api_key, config.embedding_base_url,
            dim=config.embedding_dim, timeout=15.0, transport=transport,
        )
        vectors = await client.embed(["你好"])
        dim = len(vectors[0])
        if dim != config.embedding_dim:
            return CheckResult("embedding", "FAILED", f"维度 {dim} ≠ 配置 {config.embedding_dim}")
        return CheckResult("embedding", "OK", f"dim={dim} 与配置一致")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("embedding", "FAILED", _http_error(exc))


async def check_rerank(
    config: Settings, transport: httpx.AsyncBaseTransport | None = None,
) -> CheckResult:
    if not _has_key(config.reranker_api_key):
        return CheckResult("rerank", "SKIPPED", "未配置 RERANKER_API_KEY")
    try:
        client = SiliconFlowRerankClient(
            config.reranker_model, config.reranker_api_key, config.reranker_base_url,
            timeout=15.0, transport=transport,
        )
        results = await client.rerank(
            "退款多久到账",
            ["保温杯容量 500ml", "退款将在 3~5 个工作日内到账"],
            top_n=2,
        )
        ordered = [r["index"] for r in results]
        if not ordered or ordered[0] != 1:  # 语义上"退款"文档应排前
            return CheckResult("rerank", "FAILED", f"语义排序异常: {ordered}")
        return CheckResult("rerank", "OK", f"语义排序正确: {ordered}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("rerank", "FAILED", _http_error(exc))


async def check_mineru(
    config: Settings, transport: httpx.AsyncBaseTransport | None = None,
) -> CheckResult:
    if not _has_key(config.mineru_api_key):
        return CheckResult("mineru", "SKIPPED", "未配置 MINERU_API_KEY")
    try:
        client = MinerUClient(config.mineru_api_key, base_url=config.mineru_base_url, timeout=15.0, transport=transport)
        resp = await client._http.get("/")  # 连通性探测：任意 HTTP 响应即可达
        return CheckResult("mineru", "OK", f"连通（HTTP {resp.status_code}）")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("mineru", "FAILED", _http_error(exc))


async def check_vision(
    config: Settings, transport: httpx.AsyncBaseTransport | None = None,
) -> CheckResult:
    demo_url = os.environ.get("DEMO_IMAGE_URL", "")
    if not demo_url:
        return CheckResult("vision", "SKIPPED", "未设置 DEMO_IMAGE_URL（演示图片 URL）")
    if not _has_key(config.mimo_api_key):
        return CheckResult("vision", "SKIPPED", "未配置 MIMO_API_KEY")
    try:
        client = OpenAIClient(config.model_vision, config.mimo_api_key, config.mimo_base_url, timeout=15.0, transport=transport)
        desc = await client.vision(demo_url, "请用一句话描述这张图片")
        if not desc.strip():
            return CheckResult("vision", "FAILED", "返回描述为空")
        return CheckResult("vision", "OK", f"描述: {desc.strip()[:40]!r}")
    except Exception as exc:  # noqa: BLE001
        return CheckResult("vision", "FAILED", _http_error(exc))


async def run_all(config: Settings) -> list[CheckResult]:
    return [
        await check_chat("deepseek_chat", config.model_main, config.deepseek_api_key, config.deepseek_base_url),
        await check_chat("mimo_chat", config.model_fallback, config.mimo_api_key, config.mimo_base_url),
        await check_embedding(config),
        await check_rerank(config),
        await check_mineru(config),
        await check_vision(config),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="真实 API 联调冒烟（H 清单，上线前检查）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args()
    results = asyncio.run(run_all(get_settings()))
    if args.json:
        print(json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2))
    else:
        print(f"{'项':<16}{'状态':<10}详情")
        for r in results:
            print(f"{r.name:<16}{r.status:<10}{r.detail}")
    failed = [r for r in results if r.status == "FAILED"]
    skipped = [r for r in results if r.status == "SKIPPED"]
    print(f"\n总结：OK={sum(1 for r in results if r.status == 'OK')} "
          f"SKIPPED={len(skipped)} FAILED={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
