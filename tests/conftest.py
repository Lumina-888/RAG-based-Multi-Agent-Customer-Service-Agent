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
"""
from __future__ import annotations

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        for mark in item.iter_markers(name="spec"):
            if mark.args:
                item.extra_keyword_matches.add(mark.args[0])
