"""Guardian 中间件：工具执行前校验参数，拦截危险调用。

规则按工具名注册（read_file 路径、web_fetch URL），命中则直接返回错误
ToolMessage、不执行真实工具；未注册的工具（如 MCP 工具）原样放行。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from app.security.guard import GuardError, validate_fetch_url, validate_read_path

logger = logging.getLogger(__name__)


def _check_read_file(args: Any) -> str | None:
    """校验 read_file 的 path 参数；被拦截时返回原因，放行时返回 None。"""
    path = args.get("path") if isinstance(args, dict) else None
    try:
        validate_read_path(path)
    except GuardError as exc:
        return str(exc)
    return None


def _check_web_fetch(args: Any) -> str | None:
    """校验 web_fetch 的 url 参数；被拦截时返回原因，放行时返回 None。"""
    url = args.get("url") if isinstance(args, dict) else None
    try:
        validate_fetch_url(url)
    except GuardError as exc:
        return str(exc)
    return None


_TOOL_GUARDS: dict[str, Callable[[Any], str | None]] = {
    "read_file": _check_read_file,
    "web_fetch": _check_web_fetch,
}


class GuardianMiddleware(AgentMiddleware):
    """在 wrap_tool_call 阶段拦截被安全策略拒绝的工具调用。"""

    @staticmethod
    def _blocked_message(request: Any) -> ToolMessage | None:
        tool_call = getattr(request, "tool_call", None) or {}
        name = str(tool_call.get("name") or "")
        guard = _TOOL_GUARDS.get(name)
        if guard is None:
            return None
        reason = guard(tool_call.get("args"))
        if reason is None:
            return None

        logger.warning("Guardian blocked tool %s: %s", name, reason)
        return ToolMessage(
            content=f"Guardian 拦截：{reason}",
            tool_call_id=str(tool_call.get("id") or "missing_tool_call_id"),
            name=name,
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        """同步入口：被拦截时直接返回错误 ToolMessage，不执行真实工具。"""
        blocked = self._blocked_message(request)
        if blocked is not None:
            return blocked
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        """异步入口：逻辑与 wrap_tool_call 一致（异步 agent 实际走这条路径）。"""
        blocked = self._blocked_message(request)
        if blocked is not None:
            return blocked
        return await handler(request)
