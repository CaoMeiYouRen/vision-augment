"""Unified JSON envelope for every tool result.

Shape::

    {
        "task_type": "reasoning" | "ocr" | "document",
        "tool_used": "vision:<channel>" | "local:<engine>",
        "code": 0-5,
        "error": null | str,
        "result": str | null,
        "confidence": float,
        "metadata": {...}
    }

Error codes (kept from the ds-vision-skill review):

    ===== =================== =====================================
    code  error_type           meaning
    ===== =================== =====================================
    0     success              ok
    1     channel_failed       所有视觉通道均失败 / 无可用通道
    2     timeout              通道超时
    3     invalid_input        输入无效 / 不可访问 / 超出限制
    4     dependency_missing   本地依赖未安装（OCR/文档引擎）
    5     internal_error       未知错误
    ===== =================== =====================================
"""

from __future__ import annotations

from typing import Any

ERROR_CODES: dict[int, str] = {
    0: "success",
    1: "channel_failed",
    2: "timeout",
    3: "invalid_input",
    4: "dependency_missing",
    5: "internal_error",
}


class VisionAugmentError(Exception):
    """Base error that maps onto the envelope's code + error fields."""

    code = 5

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ChannelFailedError(VisionAugmentError):
    code = 1


class ChannelTimeoutError(VisionAugmentError):
    code = 2


class InvalidInputError(VisionAugmentError):
    code = 3


class DependencyMissingError(VisionAugmentError):
    code = 4


class InternalError(VisionAugmentError):
    code = 5


def ok(
    task_type: str,
    tool_used: str,
    result: str,
    confidence: float,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "task_type": task_type,
        "tool_used": tool_used,
        "code": 0,
        "error": None,
        "result": result,
        "confidence": float(confidence),
        "metadata": metadata or {},
    }


def err(task_type: str, error: VisionAugmentError, tool_used: str = "") -> dict[str, Any]:
    return {
        "task_type": task_type,
        "tool_used": tool_used,
        "code": error.code,
        "error": error.message,
        "result": None,
        "confidence": 0.0,
        "metadata": {"error_type": ERROR_CODES.get(error.code, "unknown")},
    }
