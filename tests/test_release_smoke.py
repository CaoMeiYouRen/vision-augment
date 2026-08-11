"""Release smoke test: build the package and exercise the wheel over stdio.

Verifies what unit tests cannot: the built artifact installs cleanly via uvx
(from a local wheel) and serves the MCP tools (initialize -> tools/list ->
call health -> error path). This is the last gate before publishing.
"""

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DIST_DIR = Path(__file__).resolve().parent.parent / "dist"


def _text_content(result) -> str:
    return "\n".join(part.text for part in result.content if getattr(part, "type", "") == "text")


def _build_wheel() -> Path:
    # Reuse an existing dist when present (release CI builds first and this
    # test then validates exactly that artifact); build only as a local fallback.
    existing = sorted(DIST_DIR.glob("*.whl"))
    if existing:
        return existing[-1]
    subprocess.run(["uv", "build"], cwd=DIST_DIR.parent, check=True, capture_output=True)
    wheels = sorted(DIST_DIR.glob("*.whl"))
    assert wheels, "uv build produced no wheel"
    return wheels[-1]


async def _smoke(wheel: Path, cache_dir: Path) -> None:
    params = StdioServerParameters(
        command="uvx",
        args=["--from", str(wheel), "vision-augment"],
        env={"VISION_AUGMENT_CACHE_DIR": str(cache_dir)},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()

        tools = await session.list_tools()
        names = [t.name for t in tools.tools]
        assert "mcp_vision_augment_vision" in names
        assert "mcp_vision_augment_health" in names
        assert "mcp_vision_augment_clear_cache" in names

        report = json.loads(_text_content(await session.call_tool("mcp_vision_augment_health", {})))
        assert report["version"]
        assert "api_key" not in str(report)

        envelope = json.loads(
            _text_content(
                await session.call_tool(
                    "mcp_vision_augment_vision",
                    {"task_type": "reasoning", "source": "C:/no/such/file.png", "task": "x"},
                )
            )
        )
        assert envelope["code"] == 3


@pytest.mark.integration
def test_wheel_installs_and_serves(tmp_path):
    asyncio.run(_smoke(_build_wheel(), tmp_path / "cache"))
