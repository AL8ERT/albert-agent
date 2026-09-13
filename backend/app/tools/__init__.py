"""工具集：内置工具；MCP 工具由 app.mcp.manager 加载后一并注入 agent。"""

from app.tools.builtins import get_current_time, read_file, web_search
from app.tools.web_fetch import web_fetch


def get_builtin_tools() -> list:
    """返回全部内置工具。"""
    return [get_current_time, web_search, read_file, web_fetch]


__all__ = [
    "get_builtin_tools",
    "get_current_time",
    "read_file",
    "web_fetch",
    "web_search",
]
