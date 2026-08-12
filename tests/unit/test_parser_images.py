"""SP-ING-005 图片理解注入：T-ING-104 ~ 106（规格）+ T-ING-107（补充）。

- T-ING-104 信息图经 llm.vision() 生成描述，以 【图N 内容：…】 注入原图位置
- T-ING-105 装饰性图片（<300px / 纯色占比高 / logo）跳过且无 LLM 调用
- T-ING-106 单文档图片理解 ≤ 20 张，超出部分跳过并计数报告
- T-ING-107 enrich_document_images：文档级管线（小节内容替换 + 图片清单保留）
"""
from __future__ import annotations

import pytest

from app.core.config import Settings
from app.ingestion.images import (
    ImageUnderstandingResult,
    classify_image,
    describe_images,
    enrich_document_images,
)
from app.ingestion.models import Document, ImageRef, Section
from app.services.llm import FakeLLM, LLMRouter


def _llm(replies: list[str] | None = None) -> LLMRouter:
    return LLMRouter(
        _settings(),
        FakeLLM("deepseek-v4-flash"),
        FakeLLM("mimo-v2.5"),
        FakeLLM("mimo-v2.5", replies=replies),
        backoff=0,
    )


def _settings() -> Settings:
    return Settings(_env_file=None, deepseek_api_key="d", mimo_api_key="m")


@pytest.mark.spec("SP-ING-005")
class TestImageUnderstanding:
    async def test_ing_104_infographic_injected(self) -> None:
        md = "# 发票\n![发票图](images/a.png)\n以下是发票详情。\n"
        images = [ImageRef(path="images/a.png", url="https://x.com/a.png", width=800, height=600)]
        llm = _llm(replies=["这是一张发票，金额 299 元"])

        result = await describe_images(md, images, llm)

        assert isinstance(result, ImageUnderstandingResult)
        assert result.described == 1
        assert result.decorative_skipped == 0
        assert "【图1 内容：这是一张发票，金额 299 元】" in result.markdown
        assert "![发票图](images/a.png)" not in result.markdown  # 已替换原图位置
        # 走 llm.vision() 封装（MODEL_VISION=mimo-v2.5），URL 透传
        assert len(llm._vision.calls) == 1  # type: ignore[attr-defined]
        assert llm._vision.calls[0]["method"] == "vision"  # type: ignore[attr-defined]
        assert llm._vision.calls[0]["image_url"] == "https://x.com/a.png"  # type: ignore[attr-defined]

    async def test_ing_105_decorative_skipped_no_llm(self) -> None:
        md = "![logo](images/logo.png)\n![小图](images/s.png)\n![纯色](images/c.png)\n![信息图](images/i.png)\n"
        images = [
            ImageRef(path="images/logo.png", is_logo=True),  # logo 类
            ImageRef(path="images/s.png", width=200, height=600),  # 宽 < 300px
            ImageRef(path="images/c.png", width=500, height=400, solid_ratio=0.95),  # 纯色占比高
            ImageRef(path="images/i.png", width=800, height=600, solid_ratio=0.2),
        ]
        llm = _llm(replies=["信息图描述"])

        result = await describe_images(md, images, llm)

        assert result.described == 1
        assert result.decorative_skipped == 3
        assert "【图1 内容：信息图描述】" in result.markdown
        assert "![" not in result.markdown  # 装饰图引用被移除
        # 仅信息图触发一次 vision 调用（装饰图零调用），url 缺省回退 path
        assert len(llm._vision.calls) == 1  # type: ignore[attr-defined]
        assert llm._vision.calls[0]["image_url"] == "images/i.png"  # type: ignore[attr-defined]

    def test_ing_105_classify_rules(self) -> None:
        """分类规则纯函数：logo / 宽高 <300 / 纯色占比高 → decorative。"""
        assert classify_image(ImageRef(path="l.png", is_logo=True)) == "decorative"
        assert classify_image(ImageRef(path="s.png", width=299, height=800)) == "decorative"
        assert classify_image(ImageRef(path="s2.png", width=800, height=200)) == "decorative"
        assert classify_image(ImageRef(path="c.png", solid_ratio=0.9)) == "decorative"
        assert classify_image(ImageRef(path="i.png", width=800, height=600)) == "info"
        # 未知元数据（MinerU 未给出宽高）→ 保守按信息图处理
        assert classify_image(ImageRef(path="u.png")) == "info"

    async def test_ing_106_over_limit_counted(self) -> None:
        n = 25
        md = "\n".join(f"![图{i}](images/{i}.png)" for i in range(n))
        images = [ImageRef(path=f"images/{i}.png", width=800, height=600) for i in range(n)]
        llm = _llm(replies=[f"描述{i}" for i in range(n)])

        result = await describe_images(md, images, llm, max_images=20)

        assert result.described == 20
        assert result.over_limit_skipped == 5  # 超出部分跳过并计数报告
        assert result.markdown.count("【图") == 20
        assert "![" not in result.markdown
        assert len(llm._vision.calls) == 20  # type: ignore[attr-defined]  # 只调用了 20 次

    async def test_ing_106_max_images_configurable(self) -> None:
        images = [ImageRef(path=f"images/{i}.png", width=800, height=600) for i in range(3)]
        md = "\n".join(f"![图{i}](images/{i}.png)" for i in range(3))
        result = await describe_images(md, images, _llm(), max_images=2)
        assert result.described == 2 and result.over_limit_skipped == 1

    async def test_ing_107_enrich_document(self) -> None:
        doc = Document(
            title="手册",
            source="a.md",
            version="1",
            sections=[
                Section(1, "甲", "甲", "普通段落\n![图x](images/x.png)\n结尾。"),
                Section(1, "乙", "乙", "无图小节。"),
            ],
            images=[ImageRef(path="images/x.png", width=900, height=700)],
        )
        enriched = await enrich_document_images(doc, _llm(replies=["图中是使用步骤"]), max_images=20)

        assert "【图1 内容：图中是使用步骤】" in enriched.sections[0].content
        assert "images/x.png" not in enriched.sections[0].content
        assert enriched.sections[1].content == "无图小节。"  # 无图小节不动
        assert enriched.images == doc.images  # 图片清单保留

    async def test_ing_107_vision_failure_counted(self) -> None:
        """vision 失败 → 移除引用并计数，不中断整体流程。"""
        md = "![图a](images/a.png)\n正文"
        images = [ImageRef(path="images/a.png", width=800, height=600)]
        router = LLMRouter(
            _settings(),
            FakeLLM("deepseek-v4-flash"),
            FakeLLM("mimo-v2.5"),
            FakeLLM("mimo-v2.5", fail_times=99),  # vision 持续失败
            backoff=0,
        )
        result = await describe_images(md, images, router)
        assert result.failed == 1
        assert result.described == 0
        assert "![" not in result.markdown
