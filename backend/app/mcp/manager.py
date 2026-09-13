"""MCP 工具加载：从用户配置读取 server 定义，转成 LangChain 工具。

进程内缓存一次加载结果（应用启动时刷新）：MCP server 的连接失败只跳过该
server 并记录日志，不影响其他 server 和内置工具。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.core.config import get_mcp_servers

logger = logging.getLogger(__name__)

# 单个 server 的工具发现超时（stdio server 冷启动可能需要几十秒）
MCP_LOAD_TIMEOUT_SECONDS = 30.0

_mcp_tools: list[BaseTool] = []


def _build_connection(server: dict[str, Any]) -> dict[str, Any]:
    """把用户配置里的 server 定义转成连接参数。"""
    command = server.get("command")
    if command:
        connection: dict[str, Any] = {"transport": "stdio", "command": str(command)}
        args = server.get("args")
        if isinstance(args, list):
            connection["args"] = [str(arg) for arg in args]
        env = server.get("env")
        if isinstance(env, dict):
            connection["env"] = {str(key): str(value) for key, value in env.items()}
        cwd = server.get("cwd")
        if cwd:
            connection["cwd"] = str(cwd)
        return connection

    url = server.get("url")
    if not url:
        raise ValueError("MCP server config requires either 'command' or 'url'")

    transport = str(
        server.get("type") or server.get("transport") or "streamable_http"
    ).lower()
    transport = {
        "http": "streamable_http",
        "streamable-http": "streamable_http",
        "streamablehttp": "streamable_http",
        "sse": "sse",
    }.get(transport, transport)

    connection = {"transport": transport, "url": str(url)}
    headers = server.get("headers")
    if isinstance(headers, dict):
        connection["headers"] = {str(key): str(value) for key, value in headers.items()}
    return connection


async def refresh_mcp_tools() -> list[BaseTool]:
    """加载全部启用的 MCP server 工具并替换进程内缓存。

    - 配置缺失或不可用：返回空列表；
    - 单个 server 失败：跳过，其余照常加载；
    - 工具名带 server 前缀（tool_name_prefix=True），避免多 server 重名冲突。
    """
    global _mcp_tools

    connections: dict[str, dict[str, Any]] = {}
    for name, server in get_mcp_servers().items():
        if server.get("enabled") is False:
            logger.info("MCP server %r is disabled; skipping", name)
            continue
        try:
            connections[name] = _build_connection(server)
        except Exception as exc:
            logger.warning("Invalid MCP server config %r: %s", name, exc)

    if not connections:
        _mcp_tools = []
        return []

    client = MultiServerMCPClient(connections, tool_name_prefix=True)
    tools: list[BaseTool] = []
    for name in connections:
        try:
            server_tools = await asyncio.wait_for(
                client.get_tools(server_name=name),
                timeout=MCP_LOAD_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.warning("Failed to load tools from MCP server %r", name, exc_info=True)
            continue
        logger.info("MCP server %r contributed %d tool(s)", name, len(server_tools))
        tools.extend(server_tools)

    _mcp_tools = tools
    return list(_mcp_tools)


def get_mcp_tools() -> list[BaseTool]:
    """返回进程内缓存的 MCP 工具（尚未初始化时为空列表）。"""
    return list(_mcp_tools)
