"""SP-ING-001 文档解析：Markdown 本地解析 + PDF/Word 走 MinerU 云端 API（mineru.net）。

- Markdown：直接解析，表格保留为 Markdown 表格字符串；页眉/页脚/页码/水印噪声去除；
  全角 ASCII 转半角（清洗规则见 `clean_markdown`）
- PDF/Word（.pdf/.docx）：经 MinerU 云端异步任务（提交 → 轮询 → 拉取 zip 内
  `full.md` + 图片），再统一清洗输出结构化文档；抽取图片走 SP-ING-005 文本化注入
- 非法格式（.txt/.html/.doc 等）抛 `UnsupportedFormatError`（fail fast）
- 单元测试全部离线：MinerU 客户端支持注入 `httpx.MockTransport`，零真实网络
"""
from __future__ import annotations

import asyncio
import base64
import collections
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import Settings, get_settings
from app.ingestion.models import Document, ImageRef, Section

#: 支持的输入格式：Markdown / PDF / Word(.docx)
SUPPORTED_EXTS = {".md", ".markdown", ".pdf", ".docx"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

#: 页码/页脚行：第 N 页 / Page N (of M) / 页码：N
_PAGE_NO_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[0-9一二三四五六七八九十百千]+\s*页"
    r"|[Pp]age\s+\d+(?:\s*(?:of|/)\s*\d+)?"
    r"|页码\s*[:：]?\s*\d+"
    r")\s*$"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_STRUCTURAL_PREFIXES = ("#", "|", ">", "-", "*", "+", "`")
#: 全角 ASCII（U+FF01~U+FF5E）→ 半角
_FULLWIDTH_TABLE = str.maketrans({chr(i): chr(i - 0xFEE0) for i in range(0xFF01, 0xFF5F)})


class UnsupportedFormatError(Exception):
    """不支持的输入格式（SP-ING-001 T-ING-103）。"""


class MinerUError(Exception):
    """MinerU 云端解析失败 / 未配置 / 超时（5001 语义前置）。"""


# ---------------------------------------------------------------- 清洗与解析

def clean_markdown(text: str) -> str:
    """清洗噪声：页码行 / 重复品牌行（页眉页脚水印）/ 全角转半角 / 空行折叠。

    - 页码行：第 N 页 / Page N / 页码：N
    - 重复短行：全文出现 ≥ 3 次、长度 ≤ 20、非 Markdown 结构行 → 视为页眉/页脚/水印去除
    - 全角 ASCII（ＡＢＣ１２３）→ 半角（ABC123）
    """
    lines = text.splitlines()
    lines = [ln for ln in lines if not _PAGE_NO_RE.match(ln)]
    counts = collections.Counter(
        ln.strip() for ln in lines if not _is_md_structural(ln.strip())
    )
    lines = [
        ln
        for ln in lines
        if not (len(ln.strip()) <= 20 and counts[ln.strip()] >= 3)
    ]
    text = "\n".join(ln.rstrip() for ln in lines).translate(_FULLWIDTH_TABLE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _is_md_structural(line: str) -> bool:
    return line.startswith(_MD_STRUCTURAL_PREFIXES) or bool(re.match(r"^\d+[.、]", line))


def _sectionize(md: str) -> list[Section]:
    """按标题层级切小节：H1/H2/H3… 各自成节，正文导言为 level=0 节。

    代码块（``` 围栏）内的 `#` 不作为标题；小节内容不含子标题行。
    """
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []  # (level, heading) 祖先链
    level, heading = 0, ""
    buf: list[str] = []
    in_fence = False

    def flush() -> None:
        nonlocal buf
        content = "\n".join(buf).strip()
        # 标题节即使无正文也保留（title / heading_path 需要）；正文导言无内容则不产出
        if content or heading:
            sections.append(
                Section(
                    level=level,
                    heading=heading,
                    heading_path=" / ".join(h for _, h in stack),
                    content=content,
                )
            )
        buf = []

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            buf.append(line)
            continue
        if not in_fence:
            m = _HEADING_RE.match(line)
            if m:
                flush()
                level = len(m.group(1))
                heading = m.group(2).strip()
                stack = [pair for pair in stack if pair[0] < level] + [(level, heading)]
                continue
        buf.append(line)
    flush()
    return sections


def parse_markdown(text: str, source: str, version: str = "") -> Document:
    """纯函数：Markdown 文本 → 结构化文档（标题取首个 H1，缺省回退 source 文件名）。"""
    cleaned = clean_markdown(text)
    sections = _sectionize(cleaned)
    title = next((s.heading for s in sections if s.level == 1), Path(source).stem) or "untitled"
    return Document(title=title, source=source, version=version or "unknown", sections=sections)


def parse_markdown_file(path: str | Path, version: str = "") -> Document:
    """读取 .md 文件（UTF-8 带 BOM 容错）并解析。"""
    p = Path(path)
    return parse_markdown(p.read_text(encoding="utf-8-sig"), str(p), version)


# ---------------------------------------------------------------- MinerU 云端适配器

@dataclass
class MinerUResult:
    """MinerU 云端解析产物：Markdown 正文 + 图片清单（SP-ING-005 输入）。"""

    markdown: str
    images: list[ImageRef]


class MinerUClient:
    """mineru.net 云端异步解析（v4 API）：

    `POST /api/v4/extract/task` 提交（文件需公网 URL；无 `public_url` 时先经
    `POST /api/v4/file-urls/batch` 申请上传地址再 PUT）→ 轮询
    `GET /api/v4/extract/task/{task_id}`（pending/running/converting → done/failed）
    → done 后下载 zip 提取 `full.md` 与图片（图片转 data URL，vision 可直接消费）。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://mineru.net",
        timeout: float = 60.0,
        poll_interval: float = 5.0,
        max_polls: int = 120,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._poll_interval = poll_interval
        self._max_polls = max_polls
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,  # 测试可注入 MockTransport
        )

    async def extract(
        self, filename: str, file_bytes: bytes, public_url: str | None = None
    ) -> MinerUResult:
        """解析单个文档：返回 Markdown 与图片清单（全程在线，测试零网络）。"""
        if public_url:
            file_url = public_url
        else:
            file_url = await self._request_upload_url(filename)
            await self._upload(file_url, file_bytes)
        task_id = await self._submit(file_url)
        return await self._poll_and_fetch(task_id)

    async def _request_upload_url(self, filename: str) -> str:
        resp = await self._http.post(
            "/api/v4/file-urls/batch",
            json={"file_names": [filename], "is_ocr": True, "enable_formula": True, "enable_table": True},
        )
        resp.raise_for_status()
        item = resp.json()["data"]["file_urls"][0]
        return item.get("upload_url") or item.get("url")

    async def _upload(self, url: str, file_bytes: bytes) -> None:
        resp = await self._http.put(url, content=file_bytes)
        resp.raise_for_status()

    async def _submit(self, file_url: str) -> str:
        resp = await self._http.post(
            "/api/v4/extract/task",
            json={"url": file_url, "is_ocr": True, "enable_formula": True, "enable_table": True},
        )
        resp.raise_for_status()
        return resp.json()["data"]["task_id"]

    async def _poll_and_fetch(self, task_id: str) -> MinerUResult:
        for _ in range(self._max_polls):
            resp = await self._http.get(f"/api/v4/extract/task/{task_id}")
            resp.raise_for_status()
            data = resp.json()["data"]
            state = data.get("state", "running")
            if state == "done":
                return self._parse_zip(await self._download_zip(data["full_zip_url"]))
            if state == "failed":
                raise MinerUError(
                    f"MinerU 解析失败 task_id={task_id}: {data.get('failed_reason', 'unknown')}"
                )
            await asyncio.sleep(self._poll_interval)
        raise MinerUError(f"MinerU 解析超时 task_id={task_id}（{self._max_polls} 次轮询未完成）")

    async def _download_zip(self, url: str) -> bytes:
        resp = await self._http.get(url)
        resp.raise_for_status()
        return resp.content

    def _parse_zip(self, data: bytes) -> MinerUResult:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            md_name = next((n for n in names if n.endswith("full.md")), None)
            if md_name is None:
                raise MinerUError("MinerU 产物缺少 full.md")
            markdown = z.read(md_name).decode("utf-8")
            images = [
                ImageRef(path=name, url=_to_data_url(name, z.read(name)))
                for name in names
                if Path(name).suffix.lower() in _IMAGE_EXTS
            ]
        return MinerUResult(markdown=markdown, images=images)

    async def aclose(self) -> None:
        await self._http.aclose()


def _to_data_url(path: str, data: bytes) -> str:
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(Path(path).suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def build_mineru(config: Settings) -> MinerUClient:
    """按配置构建 MinerU 客户端；缺 `MINERU_API_KEY` 启动即失败（fail fast）。"""
    if not config.mineru_api_key:
        raise MinerUError("未配置 MINERU_API_KEY，无法调用 MinerU 云端解析（见 .env.example）")
    return MinerUClient(
        api_key=config.mineru_api_key,
        base_url=config.mineru_base_url,
        timeout=config.llm_timeout,
    )


# ---------------------------------------------------------------- 统一入口

async def parse(
    path: str | Path, version: str = "", mineru: MinerUClient | None = None
) -> Document:
    """解析入口：Markdown 本地解析；PDF/Word 经 MinerU 云端（`source` 为文件路径）。"""
    p = Path(path)
    return await parse_bytes(p.name, p.read_bytes(), version, mineru, source=str(p))


async def parse_bytes(
    filename: str,
    data: bytes,
    version: str = "",
    mineru: MinerUClient | None = None,
    source: str | None = None,
) -> Document:
    """按字节解析（KB 上传 API 使用）：扩展名决定本地 / MinerU 路径。"""
    ext = Path(filename).suffix.lower()
    if ext in {".md", ".markdown"}:
        return parse_markdown(data.decode("utf-8-sig"), source or filename, version)
    if ext in {".pdf", ".docx"}:
        if mineru is None:
            mineru = build_mineru(get_settings())
        result = await mineru.extract(Path(filename).name, data)
        doc = parse_markdown(result.markdown, source or filename, version)
        doc.images = result.images
        return doc
    raise UnsupportedFormatError(
        f"不支持的文件格式: {ext or '(无扩展名)'}（支持 {sorted(SUPPORTED_EXTS)}）"
    )
