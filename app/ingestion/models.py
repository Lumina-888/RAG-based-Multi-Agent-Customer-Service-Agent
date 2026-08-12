"""M1 文档解析与索引的领域模型（SP-ING-001/002/003/005 共用）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Section:
    """结构化小节：标题层级 + 祖先路径 + Markdown 正文。

    - `level`：H1=1；正文导言（标题前内容）= 0
    - `heading_path`："H1 / H2" 祖先路径，供分块元数据使用（SP-ING-002）
    - `content`：本小节下的 Markdown 正文（表格保留为表格字符串）
    """

    level: int
    heading: str
    heading_path: str
    content: str


@dataclass
class Document:
    """解析产物（SP-ING-001）：`Document{title, source, version, sections[]}`。"""

    title: str
    source: str
    version: str
    sections: list[Section] = field(default_factory=list)
    #: MinerU 云端解析抽取的图片清单（SP-ING-005 图片理解注入的输入）
    images: list["ImageRef"] = field(default_factory=list)


@dataclass
class ImageRef:
    """文档图片引用（SP-ING-005）。

    - `path`：Markdown 中的引用路径（`![](path)`）
    - `url`：vision 可消费地址（http / data URL），空串时回退 path
    - `width/height/solid_ratio/is_logo`：装饰性判定依据；0/未知 按信息图保守处理
    """

    path: str
    url: str = ""
    width: int = 0
    height: int = 0
    solid_ratio: float = 0.0
    is_logo: bool = False


@dataclass
class Chunk:
    """分块产物（SP-ING-002）：确定性 `_id=doc_id-seq`（SP-ING-003 幂等依据）。"""

    doc_id: str
    seq: int
    title: str
    source: str
    heading_path: str
    content: str
    tokens: int
