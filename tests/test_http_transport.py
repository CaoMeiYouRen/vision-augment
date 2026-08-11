"""Integration test: streamable-http transport serves the MCP protocol.

Starts the real server in a subprocess, completes the MCP initialize
handshake over HTTP, then verifies tools/list exposes our tools.
"""

import json
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

PROTOCOL_VERSION = "2025-06-18"

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "vision-augment-test", "version": "1.0"},
    },
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(url: str, timeout: float = 30.0) -> None:
    # NOTE: an empty-params initialize makes the mcp SDK hang the request, so
    # the readiness probe must carry a well-formed initialize payload.
    deadline = time.time() + timeout
    with httpx.Client(timeout=5) as client:
        while time.time() < deadline:
            try:
                response = client.post(
                    url,
                    json=_INITIALIZE,
                    headers={"Accept": "application/json, text/event-stream"},
                )
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
    pytest.fail("http server did not become ready")


def _sse_json(text: str) -> dict:
    data = "\n".join(
        line.removeprefix("data: ") for line in text.splitlines() if line.startswith("data: ")
    )
    return json.loads(data)


def test_streamable_http_serves_mcp(tmp_path):
    port = _free_port()
    env = {
        **os.environ,
        "VISION_AUGMENT_TRANSPORT": "streamable-http",
        "VISION_AUGMENT_PORT": str(port),
        "VISION_AUGMENT_HOST": "127.0.0.1",
        "VISION_AUGMENT_CACHE_DIR": str(tmp_path),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "vision_augment"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        url = f"http://127.0.0.1:{port}/mcp"
        _wait_until_ready(url)
        with httpx.Client(timeout=10) as client:
            response = client.post(
                url,
                json=_INITIALIZE,
                headers={"Accept": "application/json, text/event-stream"},
            )
            assert response.status_code == 200
            result = _sse_json(response.text)["result"]
            assert result["serverInfo"]["name"] == "vision-augment"

            session_id = response.headers.get("mcp-session-id")
            assert session_id, "server did not return a session id"

            tools = client.post(
                url,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": PROTOCOL_VERSION,
                    "Mcp-Session-Id": session_id,
                },
            )
            assert tools.status_code == 200
            names = [tool["name"] for tool in _sse_json(tools.text)["result"]["tools"]]
            assert "mcp_vision_augment_vision" in names
            assert "mcp_vision_augment_clear_cache" in names
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
