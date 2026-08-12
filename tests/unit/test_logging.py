"""SP-CFG-002 统一日志：T-CFG-201 / T-CFG-202。

- T-CFG-201 日志为 JSON 格式且必含 trace_id / ts / level / module
- T-CFG-202 敏感字段（手机号、订单号）自动打码
"""
from __future__ import annotations

import io
import json
import logging

import pytest

from app.core.logging import JsonFormatter, get_logger, mask_sensitive


def _capture_logger(name: str = "test_logging") -> tuple[logging.Logger, io.StringIO]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, buf


@pytest.mark.spec("SP-CFG-002")
class TestJsonLog:
    def test_cfg_201_json_schema_with_trace_id(self) -> None:
        logger, buf = _capture_logger()
        logger.info("hello", extra={"trace_id": "t_abc123"})
        record = json.loads(buf.getvalue().strip())
        # 必含四键：trace_id / ts / level / module
        for key in ("trace_id", "ts", "level", "module"):
            assert key in record, f"缺少必含字段: {key}"
        assert record["level"] == "INFO"
        assert record["module"] == "test_logging"
        assert record["trace_id"] == "t_abc123"
        assert record["message"] == "hello"

    def test_cfg_201_exc_info_serialized(self) -> None:
        """异常栈以 JSON 字段输出，不影响 JSON 合法性。"""
        logger, buf = _capture_logger()
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("处理失败")
        record = json.loads(buf.getvalue().strip())
        assert "exc_info" in record
        assert "ValueError" in record["exc_info"]
        assert record["level"] == "ERROR"

    def test_cfg_201_setup_logging_idempotent(self) -> None:
        """setup_logging 挂载 JSON handler 且幂等（重复调用不重复添加）。"""
        from app.core.logging import setup_logging

        handler = setup_logging(logging.DEBUG)
        root = logging.getLogger()
        assert handler in root.handlers
        count = len(root.handlers)
        setup_logging()  # 再次调用不重复添加
        assert len(root.handlers) == count

    def test_cfg_201_logger_adapter_injects_trace_id(self) -> None:
        """get_logger(name, trace_id) 注入 trace_id，缺省时为空串。"""
        logger, buf = _capture_logger()
        adapter = get_logger("test_logging", trace_id="t_req_01")
        adapter.info("请求处理完成")
        record = json.loads(buf.getvalue().strip())
        assert record["trace_id"] == "t_req_01"

    def test_cfg_202_mask_phone_and_order(self) -> None:
        logger, buf = _capture_logger()
        logger.info("用户手机 13812345678 的订单 ORD-20260811-001 已发货")
        message = json.loads(buf.getvalue().strip())["message"]
        # 手机号保留前 3 后 4
        assert "138****5678" in message
        assert "13812345678" not in message
        # 订单号整体打码
        assert "ORD-****" in message
        assert "ORD-20260811-001" not in message

    def test_cfg_202_mask_no_false_positive(self) -> None:
        """无敏感字段时文本原样保留。"""
        assert mask_sensitive("正常日志文本 100 条") == "正常日志文本 100 条"
        assert mask_sensitive("订单 12 号") == "订单 12 号"
