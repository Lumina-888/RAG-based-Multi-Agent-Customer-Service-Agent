"""SP-ING-001 文档解析：T-ING-101 ~ 103（规格）+ T-ING-107 ~ 110（MinerU 适配器补充）。

- T-ING-101 表格保留：parse → Document{sections[]}，表格为 Markdown 表格字符串
- T-ING-102 噪声去除：页码行 / 重复品牌行（页眉页脚水印）/ 全角转半角
- T-ING-103 非法扩展名抛 UnsupportedFormatError
- T-ING-107 MinerU 适配器（public_url 路径）：提交→轮询→拉取 zip 内 full.md + 图片（MockTransport，零网络）
- T-ING-108 MinerU 适配器（上传 URL 路径）：file-urls/batch → PUT → 提交同一 URL
- T-ING-109 MinerU 失败 / 轮询超时 → MinerUError
- T-ING-110 未配置 MINERU_API_KEY → MinerUError（fail fast）
"""
from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from app.ingestion.models import ImageRef
from app.ingestion.parser import (
    MinerUClient,
    MinerUError,
    UnsupportedFormatError,
    build_mineru,
    parse,
    parse_markdown,
)

#: 含表格 / 页眉页脚 / 全角字符的示例文档（清洗前）
MD_WITH_TABLE = """XX科技有限公司
# 售后政策
## 退货规则
| 场景 | 时限 | 说明 |
|---|---|---|
| 未发货 | 随时 | 仅支持仅退款 |
| 已签收 | 7 天 | 无理由退货 |

第 3 页
## 退款流程
请在 App 内提交申请，审核通过后原路退回。
商品编号：ＡＢＣ１２３

XX科技有限公司
# 商品常见问题
Q: 退款多久到账？
A: 一般 3~5 个工作日。

XX科技有限公司
"""


@pytest.mark.spec("SP-ING-001")
class TestMarkdownParser:
    def test_ing_101_table_preserved(self) -> None:
        """表格保留为 Markdown 表格字符串，且结构（标题/路径）正确。"""
        doc = parse_markdown(MD_WITH_TABLE, source="售后政策.md", version="1.0")

        assert doc.title == "售后政策"  # 第一个 H1
        assert doc.source == "售后政策.md"
        assert doc.version == "1.0"

        # 表格完整保留在"退货规则"小节内
        section = next(s for s in doc.sections if s.heading == "退货规则")
        assert section.level == 2
        assert section.heading_path == "售后政策 / 退货规则"  # H1 / H2 路径
        assert "| 场景 | 时限 | 说明 |" in section.content
        assert "| 未发货 | 随时 | 仅支持仅退款 |" in section.content

        # 正文小节不被表格吞并
        flow = next(s for s in doc.sections if s.heading == "退款流程")
        assert "请在 App 内提交申请" in flow.content

    def test_ing_101_preamble_and_title_fallback(self) -> None:
        """无 H1 时 title 回退 source 文件名（stem）；正文前的导言作为 level=0 小节。"""
        doc = parse_markdown("导言内容\n\n## 二级标题\n正文", source="x.md")
        assert doc.title == "x"
        preambles = [s for s in doc.sections if s.level == 0]
        assert len(preambles) == 1 and "导言内容" in preambles[0].content

    def test_ing_102_noise_removed(self) -> None:
        """页眉/页脚/水印与页码行被去除，全角 ASCII 转半角。"""
        doc = parse_markdown(MD_WITH_TABLE, source="售后政策.md")

        all_text = "\n".join(s.content for s in doc.sections)
        assert "XX科技有限公司" not in all_text  # 重复品牌行（≥3 次）已去除
        assert "第 3 页" not in all_text  # 页码行已去除
        assert "ABC123" in all_text  # 全角 ＡＢＣ１２３ → 半角
        assert "ＡＢＣ１２３" not in all_text

    def test_ing_102_page_number_variants(self) -> None:
        """常见页码/页脚形态均被去除。"""
        noisy = (
            "# 标题\n正文\n第12页\nPage 3\nPage 4 of 10\n页码：5\n页脚品牌行\n"
            "# 第二节\n内容\n"
        )
        doc = parse_markdown(noisy, source="n.md")
        all_text = "\n".join(s.content for s in doc.sections)
        for fragment in ("第12页", "Page 3", "Page 4 of 10", "页码：5"):
            assert fragment not in all_text
        assert "页脚品牌行" in all_text  # 只出现 1 次的短行保留

    def test_ing_102_fence_protected_heading(self) -> None:
        """代码块内的 # 不被当作标题。"""
        md = "# 真标题\n```\n# 代码注释\n```\n正文"
        doc = parse_markdown(md, source="f.md")
        headings = [s.heading for s in doc.sections]
        assert headings == ["真标题"]  # 代码块内 # 不产生新小节

    async def test_ing_103_unsupported_format(self, tmp_path) -> None:
        p = tmp_path / "doc.txt"
        p.write_text("plain", encoding="utf-8")
        with pytest.raises(UnsupportedFormatError):
            await parse(str(p))

        html = tmp_path / "doc.html"
        html.write_text("<p>x</p>", encoding="utf-8")
        with pytest.raises(UnsupportedFormatError):
            await parse(str(html))

        legacy = tmp_path / "doc.doc"  # 旧版 Word 不支持，仅 .docx
        legacy.write_bytes(b"\xd0\xcf\x11\xe0")
        with pytest.raises(UnsupportedFormatError):
            await parse(str(legacy))

    async def test_ing_101_parse_markdown_file(self, tmp_path) -> None:
        """parse(path) 对 .md 走本地解析并带 BOM 容错。"""
        p = tmp_path / "手册.md"
        p.write_bytes(("\ufeff" + MD_WITH_TABLE).encode("utf-8"))
        doc = await parse(str(p), version="2.1")
        assert doc.title == "售后政策"
        assert doc.version == "2.1"
        assert doc.source == str(p)


def _make_zip(md: str, images: dict[str, bytes] | None = None) -> bytes:
    """构造 MinerU 产物 zip：full.md + images/*。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("full.md", md)
        for name, data in (images or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


ZIP_BYTES = _make_zip(
    "# MinerU 解析结果\n| A | B |\n|---|---|\n| 1 | 2 |\n",
    {"images/a.png": b"\x89PNG-fake", "images/b.jpg": b"jpeg-fake"},
)


class _Recorder:
    """记录提交/轮询/上传的请求，便于断言适配器行为。"""

    def __init__(self, states: list[str] | None = None, zip_bytes: bytes = ZIP_BYTES):
        self.states: list[str] = list(states or ["done"])
        self.zip_bytes = zip_bytes
        self.submit_bodies: list[dict] = []
        self.put_urls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v4/file-urls/batch" and request.method == "POST":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"batch_id": "b1", "file_urls": [
                    {"url": "https://upload.example.com/put/sample.pdf"}]}},
            )
        if request.url.path == "/api/v4/extract/task" and request.method == "POST":
            self.submit_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task-1"}})
        if request.url.path.startswith("/api/v4/extract/task/"):
            state = self.states.pop(0) if self.states else "running"
            body = {"code": 0, "data": {"state": state}}
            if state == "done":
                body["data"]["full_zip_url"] = "https://download.example.com/result.zip"
            return httpx.Response(200, json=body)
        if request.url.host == "download.example.com":
            return httpx.Response(200, content=self.zip_bytes)
        if request.method == "PUT":
            self.put_urls.append(str(request.url))
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(404, json={"code": -1})


@pytest.mark.spec("SP-ING-001")
class TestMinerUAdapter:
    def _client(self, rec: _Recorder, **kw) -> MinerUClient:
        params = dict(
            api_key="mineru-test",
            base_url="https://mineru.net",
            timeout=10.0,
            poll_interval=0,
            max_polls=10,
            transport=httpx.MockTransport(rec.handler),
        )
        params.update(kw)
        return MinerUClient(**params)

    async def test_ing_107_extract_with_public_url(self) -> None:
        """public_url 路径：提交 → 轮询 done → 下载 zip → full.md + 图片清单。"""
        rec = _Recorder()
        result = await self._client(rec).extract(
            "sample.pdf", b"%PDF-fake", public_url="https://s3.example.com/sample.pdf"
        )

        assert "MinerU 解析结果" in result.markdown
        assert "| 1 | 2 |" in result.markdown  # MinerU 表格保留
        # 提交体使用 public_url，且轮询到 done 才拉取
        assert rec.submit_bodies[0]["url"] == "https://s3.example.com/sample.pdf"
        assert rec.submit_bodies[0]["is_ocr"] is True
        # 图片清单：path + data URL（vision 可直接消费）
        assert [img.path for img in result.images] == ["images/a.png", "images/b.jpg"]
        assert result.images[0].url.startswith("data:image/png;base64,")
        assert result.images[1].url.startswith("data:image/jpeg;base64,")

    async def test_ing_108_extract_with_upload_url(self) -> None:
        """无 public_url：file-urls/batch 取上传 URL → PUT 文件 → 提交同一 URL。"""
        rec = _Recorder()
        result = await self._client(rec).extract("sample.docx", b"docx-fake")

        assert rec.put_urls == ["https://upload.example.com/put/sample.pdf"]
        assert rec.submit_bodies[0]["url"] == "https://upload.example.com/put/sample.pdf"
        assert len(result.images) == 2

    async def test_ing_109_failed_state_and_timeout(self) -> None:
        rec = _Recorder(states=["running", "failed"])
        client = self._client(rec)
        with pytest.raises(MinerUError, match="失败"):
            await client.extract("a.pdf", b"x", public_url="https://x/a.pdf")

        rec2 = _Recorder(states=["running"])
        client2 = self._client(rec2, max_polls=3)
        with pytest.raises(MinerUError, match="超时|timeout"):
            await client2.extract("a.pdf", b"x", public_url="https://x/a.pdf")

    def test_ing_110_missing_api_key_fails_fast(self) -> None:
        from app.core.config import Settings

        settings = Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m")
        with pytest.raises(MinerUError, match="MINERU_API_KEY"):
            build_mineru(settings)

    def test_ing_110_image_ref_defaults(self) -> None:
        """ImageRef 元数据默认值：未知宽高/纯色占比 → 按信息图处理（classify 见 SP-ING-005）。"""
        img = ImageRef(path="images/x.png")
        assert img.width == 0 and img.height == 0
        assert img.solid_ratio == 0.0 and img.is_logo is False
