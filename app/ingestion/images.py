"""SP-ING-005 图片理解注入：图片不可被 BM25/向量检索，必须文本化。

- 装饰性图片（宽高 < 300px / 纯色占比高 / logo 类）跳过，不调用 LLM
- 信息图（截图/表单/流程图等）经 `llm.vision()`（MODEL_VISION=mimo-v2.5）生成
  结构化描述，以 `【图N 内容：…】` 文本块替换注入原图位置
- 单文档图片理解数 ≤ 20 张，超出部分跳过并计数报告
- 图片理解走 SP-CFG-004 的 `llm.vision()` 封装，FakeLLM 可注入，单测零真实 API
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.ingestion.models import Document, ImageRef, Section

#: vision 提示词：要求结构化、不臆测
VISION_PROMPT = (
    "你是文档解析助手。请用简洁的中文描述这张图片中的信息内容；"
    "若为表格/流程图/表单/截图，请尽量保留结构与要点，不要臆测不存在的内容。"
)

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)")

DECORATIVE = "decorative"
INFO = "info"

#: 单文档图片理解数上限（SP-ING-005）
MAX_IMAGES_PER_DOC = 20

#: 纯色占比 ≥ 0.8 视为装饰性图片
SOLID_RATIO_THRESHOLD = 0.8
#: 宽或高 < 300px 视为装饰性图片
MIN_INFO_SIZE_PX = 300


def classify_image(img: ImageRef) -> str:
    """装饰性判定（纯函数）：logo / 宽高 < 300px / 纯色占比高 → decorative。

    元数据未知（宽高为 0 等）时保守按信息图处理（宁多描述，不漏信息）。
    """
    if img.is_logo:
        return DECORATIVE
    if img.width > 0 and (img.width < MIN_INFO_SIZE_PX or img.height < MIN_INFO_SIZE_PX):
        return DECORATIVE
    if img.solid_ratio >= SOLID_RATIO_THRESHOLD:
        return DECORATIVE
    return INFO


class VisionProvider(Protocol):
    """llm.vision 封装协议（SP-CFG-004 的 LLMRouter 即满足）。"""

    async def vision(self, image_url: str, prompt: str, **kwargs: Any) -> Any: ...


@dataclass
class ImageUnderstandingResult:
    """图片理解结果：替换后的 Markdown + 各类计数报告（超限/失败均可追溯）。"""

    markdown: str
    described: int = 0
    decorative_skipped: int = 0
    over_limit_skipped: int = 0
    failed: int = 0


async def describe_images(
    markdown: str, images: list[ImageRef], llm: VisionProvider, max_images: int = MAX_IMAGES_PER_DOC
) -> ImageUnderstandingResult:
    """对 Markdown 中引用的图片执行理解注入：`![](path)` → `【图N 内容：…】`。"""
    by_path = {img.path: img for img in images}
    result = ImageUnderstandingResult(markdown=markdown)

    async def replace(match: re.Match) -> str:
        img = by_path.get(match.group(2))
        if img is None:
            return match.group(0)  # 无元数据：保留原引用，不臆断
        if classify_image(img) == DECORATIVE:
            result.decorative_skipped += 1
            return ""
        if result.described >= max_images:
            result.over_limit_skipped += 1
            return ""
        try:
            chat = await llm.vision(img.url or img.path, VISION_PROMPT)
        except Exception:  # noqa: BLE001 - 单图失败不中断整篇
            result.failed += 1
            return ""
        result.described += 1
        desc = chat.content if hasattr(chat, "content") else str(chat)
        return f"【图{result.described} 内容：{desc.strip()}】"

    # 手动迭代替换（re.sub 不支持 async 替换函数）
    out: list[str] = []
    pos = 0
    for m in _IMG_RE.finditer(markdown):
        out.append(markdown[pos : m.start()])
        out.append(await replace(m))
        pos = m.end()
    out.append(markdown[pos:])
    result.markdown = "".join(out)
    return result


async def enrich_document_images(
    doc: Document, llm: VisionProvider, max_images: int = MAX_IMAGES_PER_DOC
) -> Document:
    """文档级管线：含图小节执行理解注入（无图小节原样保留，图片清单透传）。"""
    new_sections: list[Section] = []
    for section in doc.sections:
        if _IMG_RE.search(section.content):
            res = await describe_images(section.content, doc.images, llm, max_images=max_images)
            new_sections.append(
                Section(section.level, section.heading, section.heading_path, res.markdown)
            )
        else:
            new_sections.append(section)
    return Document(doc.title, doc.source, doc.version, new_sections, doc.images)
