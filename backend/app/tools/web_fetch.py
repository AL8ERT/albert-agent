"""web_fetch 工具：抓取白名单域名的 https 页面并转成 Markdown / 纯文本。

- 仅 https + 白名单域名（配置见 app.core.config.get_web_fetch_allowed_domains）；
- 逐跳校验重定向，防止跳转到未授权地址；
- HTML 去脚本/导航后转 Markdown，页面内链接统一转成绝对 URL，方便模型继续抓取；
- 响应上限 1MB、返回正文按 max_chars 截断。
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from langchain_core.tools import tool
from markdownify import markdownify

from app.security.guard import GuardError, validate_fetch_url

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 15.0
MAX_FETCH_BYTES = 1_000_000
MAX_REDIRECTS = 5
DEFAULT_MAX_CHARS = 20_000
MAX_MAX_CHARS = 100_000

_ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
    "application/json",
    "application/xml",
    "text/xml",
}
_STRIP_TAGS = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "noscript",
    "svg",
    "form",
    "iframe",
    "img",
)
_USER_AGENT = "albert-agent/0.1"


def _html_to_markdown(body: bytes, base_url: str) -> str:
    """HTML 转 Markdown；剔除噪音标签并把链接转成绝对地址。"""
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(list(_STRIP_TAGS)):
        tag.decompose()
    for anchor in soup.find_all("a", href=True):
        anchor["href"] = urljoin(base_url, anchor["href"])
    markdown = markdownify(str(soup), heading_style="ATX")
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()


def _fetch(url: str) -> tuple[str, str, bytes]:
    """抓取 URL，逐跳校验重定向，返回 (final_url, content_type, body)。"""
    current = validate_fetch_url(url)
    timeout = httpx.Timeout(FETCH_TIMEOUT_SECONDS, connect=5.0)
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,text/plain,application/json,application/xml;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(
        follow_redirects=False, timeout=timeout, headers=headers
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream("GET", current) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise GuardError("重定向缺少 Location")
                    current = validate_fetch_url(urljoin(current, location))
                    continue
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_FETCH_BYTES:
                        raise GuardError(f"页面超过 {MAX_FETCH_BYTES} 字节上限")
                    chunks.append(chunk)
                return str(response.url), content_type, b"".join(chunks)
    raise GuardError("重定向次数过多")


def _format_body(body: bytes, content_type: str, base_url: str, max_chars: int) -> str:
    """把响应体转成给模型看的文本。"""
    if not content_type:
        content_type = "text/plain"
    if content_type in {"text/html", "application/xhtml+xml"}:
        text = _html_to_markdown(body, base_url)
    elif content_type in _ALLOWED_CONTENT_TYPES:
        text = body.decode("utf-8", errors="replace")
    else:
        return f"不支持的内容类型：{content_type}"

    if not text.strip():
        return "（页面没有可提取的文本内容）"
    if len(text) > max_chars:
        return text[:max_chars] + f"\n\n...（已截断，原文约 {len(text)} 字符）"
    return text


@tool
def web_fetch(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """抓取网页正文；HTML 会转成 Markdown，链接为绝对地址，可用返回的链接继续抓取。

    仅允许访问 https 且位于配置白名单（webFetchAllowedDomains）内的域名。

    Args:
        url: 要抓取的完整 URL（必须 https）。
        max_chars: 返回正文的最大字符数（默认 20000，上限 100000）。
    """
    max_chars = max(1000, min(int(max_chars), MAX_MAX_CHARS))
    try:
        final_url, content_type, body = _fetch(url)
    except GuardError as exc:
        return f"Guardian 拦截：{exc}"
    except httpx.HTTPStatusError as exc:
        return f"抓取失败：HTTP {exc.response.status_code}"
    except httpx.HTTPError as exc:
        logger.warning("web_fetch failed for %s: %s", url, exc)
        return f"抓取失败：{exc}"

    text = _format_body(body, content_type, final_url, max_chars)
    if final_url != url:
        return f"[redirected to {final_url}]\n\n{text}"
    return text
