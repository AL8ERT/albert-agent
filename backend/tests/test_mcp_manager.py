"""MCP 管理器测试：连接配置转换与失败隔离（不启动真实 MCP server）。"""

import asyncio
from collections.abc import Iterator

import pytest
from pytest import MonkeyPatch

from app.mcp import manager


@pytest.fixture(autouse=True)
def _reset_tool_cache() -> Iterator[None]:
    """每个用例前后重置进程内工具缓存，避免用例互相影响。"""
    manager._mcp_tools = []
    yield
    manager._mcp_tools = []


def test_build_connection_stdio() -> None:
    connection = manager._build_connection(
        {"command": "npx", "args": ["-y", "@playwright/mcp@latest"], "env": {"TOKEN": 1}}
    )

    assert connection == {
        "transport": "stdio",
        "command": "npx",
        "args": ["-y", "@playwright/mcp@latest"],
        "env": {"TOKEN": "1"},
    }


def test_build_connection_remote_variants() -> None:
    assert manager._build_connection(
        {"url": "https://mcp.example.com/mcp", "type": "http", "headers": {"A": "b"}}
    ) == {
        "transport": "streamable_http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"A": "b"},
    }
    assert manager._build_connection({"url": "https://x/sse", "transport": "sse"}) == {
        "transport": "sse",
        "url": "https://x/sse",
    }


def test_build_connection_requires_target() -> None:
    with pytest.raises(ValueError):
        manager._build_connection({"enabled": True})


def test_refresh_mcp_tools_isolates_failures(monkeypatch: MonkeyPatch) -> None:
    """坏 server 只跳过自己；禁用/非法配置不进入连接列表。"""
    connections_seen: list[dict] = []

    class _FakeClient:
        def __init__(self, connections: dict, **kwargs: object) -> None:
            connections_seen.append(dict(connections))

        async def get_tools(self, *, server_name: str) -> list[str]:
            if server_name == "broken":
                raise RuntimeError("connect failed")
            return [f"tool-from-{server_name}"]

    monkeypatch.setattr(manager, "MultiServerMCPClient", _FakeClient)
    monkeypatch.setattr(
        manager,
        "get_mcp_servers",
        lambda: {
            "good": {"command": "echo"},
            "broken": {"command": "false"},
            "disabled": {"command": "echo", "enabled": False},
            "invalid": {"foo": "bar"},
        },
    )

    tools = asyncio.run(manager.refresh_mcp_tools())

    assert tools == ["tool-from-good"]
    assert manager.get_mcp_tools() == ["tool-from-good"]
    assert set(connections_seen[0]) == {"good", "broken"}


def test_refresh_mcp_tools_without_servers(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(manager, "get_mcp_servers", lambda: {})

    assert asyncio.run(manager.refresh_mcp_tools()) == []
    assert manager.get_mcp_tools() == []
