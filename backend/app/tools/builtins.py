"""内置工具：当前时间、网页搜索与文件读取。

这些工具与 MCP 工具一样直接挂到 create_agent 的 tools 列表里；
网页搜索走 DuckDuckGo（ddgs），无需 API Key。
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ddgs import DDGS
from langchain_core.tools import tool

from app.security.guard import GuardError, validate_read_path

logger = logging.getLogger(__name__)

# 单次读取上限：超过则拒绝，避免把大文件/二进制塞进上下文
MAX_READ_BYTES = 2_000_000
MAX_READ_LINES = 2000


@tool
def get_current_time(timezone: str | None = None) -> str:
    """获取当前日期和时间。

    Args:
        timezone: 可选 IANA 时区名（如 Asia/Shanghai、America/New_York），
            缺省使用运行环境的本地时区。
    """
    try:
        now = (
            datetime.now(ZoneInfo(timezone))
            if timezone
            else datetime.now().astimezone()
        )
    except (ZoneInfoNotFoundError, ValueError):
        return f"未知时区：{timezone}"
    return now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """搜索互联网，返回若干条网页的标题、链接与摘要。

    Args:
        query: 搜索关键词。
        max_results: 返回结果条数（1-10，默认 5）。
    """
    max_results = max(1, min(int(max_results), 10))
    try:
        results = DDGS().text(query, max_results=max_results)
    except Exception as exc:
        # 网络/搜索后端错误作为工具结果返回，让模型决定是否重试
        logger.warning("web_search failed: %s", exc)
        return f"搜索失败：{exc}"

    if not results:
        return "没有找到相关结果。"

    lines: list[str] = []
    for index, item in enumerate(results, start=1):
        title = str(item.get("title") or "").strip()
        href = str(item.get("href") or "").strip()
        body = " ".join(str(item.get("body") or "").split())
        lines.append(f"{index}. {title}\n   {href}\n   {body}")
    return "\n".join(lines)


@tool
def read_file(path: str, offset: int = 0, limit: int = MAX_READ_LINES) -> str:
    """读取文本文件内容（用于查看 SKILL.md、配置文件、代码等）。

    Args:
        path: 文件路径，支持 ~ 展开。
        offset: 起始行号（从 0 开始，默认 0）。
        limit: 最多返回的行数（默认 2000）。
    """
    try:
        target = validate_read_path(path)
    except GuardError as exc:
        return f"Guardian 拦截：{exc}"

    if not target.is_file():
        return f"无法读取：{path} 不存在或不是文件。"
    try:
        if target.stat().st_size > MAX_READ_BYTES:
            return f"文件过大（超过 {MAX_READ_BYTES} 字节），请改用更精确的路径。"
        raw = target.read_bytes()
    except OSError as exc:
        logger.warning("read_file failed for %s: %s", path, exc)
        return f"读取失败：{exc}"

    if b"\x00" in raw[:8192]:
        return f"无法读取二进制文件：{path}"

    lines = raw.decode("utf-8", errors="replace").splitlines()
    offset = max(0, int(offset))
    limit = max(1, int(limit))
    selected = lines[offset : offset + limit]
    if not selected:
        return f"（没有内容：起始行 {offset} 超出文件共 {len(lines)} 行）"

    body = "\n".join(selected)
    remaining = len(lines) - (offset + len(selected))
    if remaining > 0:
        body += f"\n...（已截断，还有 {remaining} 行未显示）"
    return body
