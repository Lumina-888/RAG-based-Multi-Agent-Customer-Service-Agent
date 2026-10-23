"""SP-ING-004 知识库管理 API：上传（异步 解析→分块→索引）与调试检索。

- `POST /api/v1/kb/documents`：上传文档，后台任务 解析（md 本地 / PDF·Word 走
  MinerU 云端）→ 图片理解注入（SP-ING-005）→ 分块 → 幂等索引，返回 `doc_id` 与状态
- `GET /api/v1/kb/documents/{doc_id}`：查询索引状态（processing/done/failed，
  状态经 DocStatusStore 记录，上传者可据此确认文档是否真正入库）
- `GET /api/v1/kb/search?q=`：调试用检索原始结果（BM25 预览；M2 交付后切换
  hybrid_search）
- 依赖 `IngestionDeps` 可被测试 dependency_overrides 注入 Fake（CI 不依赖真实 API）
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.responses import err, ok
from app.ingestion.chunker import chunk
from app.ingestion.images import enrich_document_images
from app.ingestion.indexer import index_chunks
from app.ingestion.parser import SUPPORTED_EXTS, MinerUClient, build_mineru, parse_bytes
from app.ingestion.status_store import DocStatusStore, RedisDocStatusStore
from app.retrieval.hybrid_search import hybrid_search
from app.services.embedding import EmbeddingClient, build_embedding_client
from app.services.es import ESClient
from app.services.llm import LLMRouter, build_llm

logger = logging.getLogger("app.api.kb")

router = APIRouter(prefix="/api/v1/kb", tags=["kb"])


@dataclass
class IngestionDeps:
    """KB 管线依赖（测试可注入 Fake / None 跳过可选环节）。"""

    es: ESClient
    embedding: EmbeddingClient
    mineru: MinerUClient | None = None
    llm: LLMRouter | None = None
    status_store: DocStatusStore | None = None


@lru_cache(maxsize=1)
def _build_deps() -> IngestionDeps:
    settings = get_settings()
    return IngestionDeps(
        es=ESClient(settings.es_host),
        embedding=build_embedding_client(settings),
        mineru=build_mineru(settings) if settings.mineru_api_key else None,
        llm=build_llm(settings),
        status_store=RedisDocStatusStore(settings.redis_url),
    )


async def _mark_status(deps: IngestionDeps, doc_id: str, status: str, **kwargs) -> None:
    """尽力而为地记录文档状态：存储不可用只记日志，不阻断主流程。"""
    if deps.status_store is None:
        return
    try:
        await deps.status_store.mark(doc_id, status, **kwargs)
    except Exception:  # noqa: BLE001 - 状态记录失败不影响上传/索引
        logger.warning("KB 文档状态记录失败 doc_id=%s status=%s", doc_id, status, exc_info=True)


def get_ingestion_deps() -> IngestionDeps:
    """KB 依赖入口：测试用 `app.dependency_overrides` 覆盖。"""
    return _build_deps()


@router.post("/documents", status_code=200)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    deps: IngestionDeps = Depends(get_ingestion_deps),
) -> dict:
    """上传文档：非法格式 4001；合法 → 后台异步解析索引，返回 doc_id + status。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTS:
        return err(
            4001, 400, f"不支持的文件格式: {ext or '(无扩展名)'}（支持 {sorted(SUPPORTED_EXTS)}）"
        )
    doc_id = uuid.uuid4().hex
    trace_id = f"t_{uuid.uuid4().hex[:16]}"
    data = await file.read()
    await _mark_status(deps, doc_id, "processing", filename=file.filename or "upload")
    background_tasks.add_task(_ingest_task, doc_id, file.filename or "upload", data, deps, trace_id)
    logger.info(
        "KB 文档上传 doc_id=%s filename=%s", doc_id, file.filename, extra={"trace_id": trace_id}
    )
    return ok({"doc_id": doc_id, "status": "processing"}, trace_id)


@router.get("/documents/{doc_id}")
async def get_document_status(
    doc_id: str,
    deps: IngestionDeps = Depends(get_ingestion_deps),
) -> dict:
    """查询文档索引状态：无记录（未知 doc_id 或记录已过期）→ 4040。"""
    if deps.status_store is None:
        return err(4040, 404, "文档状态不存在或已过期")
    record = await deps.status_store.get(doc_id)
    if record is None:
        return err(4040, 404, "文档状态不存在或已过期")
    return ok(record)


@router.get("/search")
async def kb_search(
    q: str = Query(min_length=1, max_length=200, description="检索词"),
    size: int = Query(10, ge=1, le=50),
    deps: IngestionDeps = Depends(get_ingestion_deps),
) -> dict:
    """调试用：查看混合检索原始结果（默认 RRF 融合，SP-RET-005）。"""
    try:
        result = await hybrid_search(
            q, deps.es, embedding=deps.embedding, strategy="rrf", top_k=size
        )
    except Exception as exc:  # noqa: BLE001 - ES 不可用统一 5002
        return err(5002, 503, f"检索服务不可用: {exc}")
    return ok(
        {
            "strategy": result["strategy"],
            "count": len(result["docs"]),
            "elapsed_ms": result["elapsed_ms"],
            "hits": result["docs"],
        }
    )


async def _ingest_task(
    doc_id: str, filename: str, data: bytes, deps: IngestionDeps, trace_id: str = ""
) -> None:
    """后台任务：解析 → 图片理解注入 → 分块 → 幂等索引（异常记日志不中断响应）。"""
    try:
        doc = await parse_bytes(filename, data, mineru=deps.mineru)
        if doc.images and deps.llm is not None:
            doc = await enrich_document_images(doc, deps.llm)
        chunks = chunk(doc, doc_id=doc_id)
        n = await index_chunks(chunks, doc_id=doc_id, es=deps.es, embedding=deps.embedding)
        await _mark_status(deps, doc_id, "done", filename=filename, chunks=n)
        logger.info(
            "KB 文档索引完成 doc_id=%s chunks=%d", doc_id, n, extra={"trace_id": trace_id}
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务兜底
        await _mark_status(
            deps, doc_id, "failed", filename=filename, error=str(exc)[:200]
        )
        logger.exception(
            "KB 文档索引失败 doc_id=%s filename=%s", doc_id, filename, extra={"trace_id": trace_id}
        )
