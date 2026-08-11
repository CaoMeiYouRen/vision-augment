"""MCP server entrypoint: exposes the vision/ocr/document tools.

Transports (select via VISION_AUGMENT_TRANSPORT):
- stdio (default): local-first, zero config — ``command: uvx, args: [vision-augment]``
- streamable-http: for Docker/remote/multi-client setups —
  ``VISION_AUGMENT_TRANSPORT=streamable-http``, binds VISION_AUGMENT_HOST:PORT
  (default 127.0.0.1:8000, endpoint /mcp). The mcp SDK auto-enables DNS
  rebinding protection when bound to localhost; exposing beyond localhost is
  the operator's call (put it behind a reverse proxy / auth).

Register with any MCP client, e.g. Hermes ``config.yaml``::

    mcp_servers:
      vision-augment:
        command: uvx
        args: [vision-augment]
        env:
          VISION_AUGMENT_CHANNELS: '[{"base_url": "...", "api_key": "...", "model": "..."}]'
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .cache import TTLCache
from .config import Settings, load_settings
from .health import check as check_health
from .router import Router

logger = logging.getLogger("vision_augment")


def build_server(settings: Settings | None = None) -> FastMCP:
    settings = settings or load_settings()
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    router = Router(settings, TTLCache(settings.cache_dir, settings.cache_ttl_seconds))
    # streamable-http request body limit must tolerate base64-inflated data: URLs
    # (SDK default is only 4MB, while inputs may be up to max_input_mb).
    max_body = settings.max_input_mb * 2 * 1024 * 1024
    mcp = FastMCP("vision-augment", host=settings.host, port=settings.port, max_request_body_size=max_body)

    @mcp.tool()
    def mcp_vision_augment_vision(
        task_type: Annotated[
            Literal["reasoning", "ocr", "document"],
            Field(description="任务类型：reasoning=视觉理解（看图问答）；ocr=图像文字识别；document=文档解析（docx/pdf/pptx/xlsx/html/md）"),
        ],
        source: Annotated[
            str,
            Field(description="输入：本地文件路径 / file:// / http(s)://（需 VISION_AUGMENT_ALLOW_URLS=true）/ data:URL"),
        ],
        task: Annotated[str, Field(description="reasoning 时的提问内容（如“请描述这张图片”），其他任务忽略", default="")] = "",
        language: Annotated[
            str,
            Field(description="OCR 语言：ch/en/japan/korea/latin，仅 ocr 任务生效", default="ch"),
        ] = "ch",
    ) -> dict:
        """多模态视觉工具：为无视觉能力的 LLM 提供看图、OCR 与文档解析能力。

        返回统一 JSON envelope：{task_type, tool_used, code, error, result, confidence, metadata}。
        视觉理解按配置的 OpenAI 兼容通道依次降级，最后兜底本地 Ollama VL 模型；
        OCR 与文档解析在本地完成（RapidOCR / markitdown）。
        """
        return router.run(task_type, source, task, language)

    @mcp.tool()
    def mcp_vision_augment_clear_cache() -> str:
        """清除本地结果缓存（缓存 TTL 上限由 VISION_AUGMENT_CACHE_TTL_SECONDS 控制）。"""
        count = router.cache.clear()
        return f"cleared {count} cached entries"

    @mcp.tool()
    def mcp_vision_augment_health() -> dict:
        """环境探测：检查视觉通道/Ollama/OCR/文档引擎的配置状态（不含密钥），
        用于向用户反馈还缺少哪些配置及对应安装命令。"""
        return check_health(settings)

    return mcp


def main() -> None:
    settings = load_settings()
    server = build_server(settings)
    if settings.transport == "streamable-http":
        server.run(transport="streamable-http")
    else:
        server.run()


if __name__ == "__main__":
    main()
