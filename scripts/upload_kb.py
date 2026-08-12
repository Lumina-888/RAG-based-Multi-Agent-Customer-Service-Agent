"""批量上传知识库（G 验证脚本）：data/raw_docs/*.md → POST /api/v1/kb/documents → 抽查搜索。

用法（M9 `docker compose up -d` 后）：
    python scripts/upload_kb.py [--base http://localhost:8000] [--wait 20]

- 上传：逐份 POST（异步 解析→分块→索引，返回 doc_id + processing）
- 抽查：等待 wait 秒后 GET /api/v1/kb/search 验证索引生效
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
RAW_DOCS = ROOT / "data" / "raw_docs"

#: 抽查查询（售后 / 商品 / FAQ 三类各一）
SPOT_CHECKS = ("退款多久到账", "保温杯容量多大", "怎么联系人工客服")


def upload_all(base: str, client: httpx.Client) -> list[str]:
    doc_ids: list[str] = []
    files = sorted(RAW_DOCS.glob("*.md"))
    for path in files:
        resp = client.post(
            f"{base}/api/v1/kb/documents",
            files={"file": (path.name, path.read_bytes(), "text/markdown")},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        doc_ids.append(data["doc_id"])
        print(f"[upload] {path.name} → doc_id={data['doc_id']} status={data['status']}")
    print(f"已提交 {len(files)} 份文档")
    return doc_ids


def spot_check(base: str, client: httpx.Client) -> None:
    print("\n== 抽查检索（等待异步索引）==")
    for q in SPOT_CHECKS:
        resp = client.get(f"{base}/api/v1/kb/search", params={"q": q, "size": 5}, timeout=15.0)
        resp.raise_for_status()
        data = resp.json()["data"]
        hits = data.get("hits", [])
        print(f"q={q!r} → strategy={data.get('strategy')} count={data.get('count')} "
              f"elapsed={data.get('elapsed_ms')}ms")
        for hit in hits[:3]:
            print(f"    - {hit.get('doc_id')} | {hit.get('title')} | score={hit.get('score')}")
        if not hits:
            print("    ! 无结果（可能仍在索引，可增大 --wait 重跑）")


def main() -> None:
    parser = argparse.ArgumentParser(description="批量上传 data/raw_docs 到知识库 API")
    parser.add_argument("--base", default="http://localhost:8000", help="应用地址")
    parser.add_argument("--wait", type=int, default=20, help="上传后等待秒数（异步索引）")
    args = parser.parse_args()

    with httpx.Client() as client:
        upload_all(args.base, client)
        print(f"等待 {args.wait}s 让异步索引完成...")
        time.sleep(args.wait)
        spot_check(args.base, client)
    print("\n知识库上传完成。下一步：python tests/bench/bench_retrieval.py（性能验收，SP-RET-006）")


if __name__ == "__main__":
    sys.exit(main())
