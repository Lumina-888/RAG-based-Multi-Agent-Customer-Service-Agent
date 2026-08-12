"""pytest 全局配置。

将 `@pytest.mark.spec("SP-CFG-001")` 的规格 ID 注册进 `extra_keyword_matches`，
支持按规格过滤运行（规格 §0.4 / §5）：
- `pytest -m spec`          跑全部 spec 标记用例
- `pytest -k "SP-CFG-001"`  按规格 ID 过滤（pytest 9 表达式语法不支持 `spec=XXX` 形式）

说明：
- pytest 9 的 `-k` 匹配器只读节点名 / extra_keyword_matches / 函数属性 / marker 名，
  不读 `item.keywords` 字典（故不能靠关键字赋值实现）；
- 内置 -k/-m 过滤在 `pytest_collection_modifyitems` 内执行，
  本 hook 需 `tryfirst=True` 抢在其之前完成注册。

集成测试共享夹具（ES 不可达时整体 skip；本机起 ES 见 M9 docker compose）：
- `es_client`：ESClient 探测可用性，不可用 skip
- `kb`：索引样例文档（FakeEmbedding dim=1024）供检索用例使用
"""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.services.es import ESClient

#: M2 检索集成测试样例文档（含 退款/退货 语义样本）
SAMPLE_DOCS: list[tuple[str, str]] = [
    (
        "kb-ret-01",
        "# 售后政策\n## 退款说明\n退款将在 3~5 个工作日内原路退回，请耐心等待。\n"
        "## 退货规则\n已签收 7 天内支持无理由退货，运费由平台承担。\n",
    ),
    (
        "kb-ret-02",
        "# 商品手册\n## 智能保温杯\n容量 500ml，保温时长 12 小时，Type-C 充电。\n",
    ),
]


@pytest.fixture
async def es_client() -> ESClient:
    client = ESClient(get_settings().es_host, timeout=3.0)
    try:
        ok = await client.ping()
    except Exception:  # noqa: BLE001 - 连接失败视为不可用
        ok = False
    if not ok:
        await client.aclose()
        pytest.skip("本机 ES 不可用（需 ES 8.x，docker compose 见 M9）")
    yield client
    await client.aclose()


@pytest.fixture
async def kb(es_client: ESClient) -> ESClient:
    """索引样例文档供检索用例使用，测试后清理。"""
    from app.ingestion.chunker import chunk
    from app.ingestion.indexer import index_chunks
    from app.ingestion.parser import parse_markdown
    from app.services.embedding import FakeEmbeddingClient

    embedding = FakeEmbeddingClient(dim=1024)
    for doc_id, md in SAMPLE_DOCS:
        await es_client.delete_by_doc_id(doc_id)
        parsed = parse_markdown(md, source=f"{doc_id}.md", version="1.0")
        await index_chunks(chunk(parsed, doc_id=doc_id), doc_id=doc_id, es=es_client, embedding=embedding)
    yield es_client
    for doc_id, _ in SAMPLE_DOCS:
        await es_client.delete_by_doc_id(doc_id)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        for mark in item.iter_markers(name="spec"):
            if mark.args:
                item.extra_keyword_matches.add(mark.args[0])
