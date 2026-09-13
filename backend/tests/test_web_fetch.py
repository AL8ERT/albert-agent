"""web_fetch 工具测试：用假 httpx Client 验证转换、重定向校验、类型与截断。"""

import importlib

import httpx
import pytest
from pytest import MonkeyPatch

from app.security import guard

# 包 __init__ 里的 web_fetch 名字被工具对象占用，这里按模块路径取模块本体
web_fetch_module = importlib.import_module("app.tools.web_fetch")


@pytest.fixture(autouse=True)
def _allow_docs_domain(monkeypatch: MonkeyPatch) -> None:
    """默认放行 docs.example.com，避免依赖真实用户配置。"""
    monkeypatch.setattr(
        guard, "get_web_fetch_allowed_domains", lambda: ("docs.example.com",)
    )


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._content = content
        self.headers = headers or {}
        self.url = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("GET", "https://placeholder.invalid"),
                response=self,  # type: ignore[arg-type]
            )

    def iter_bytes(self) -> object:
        yield self._content


class _FakeStream:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeResponse:
        return self._response

    def __exit__(self, *exc: object) -> bool:
        return False


class _FakeClient:
    """按队列顺序返回预置响应；记录实际请求的 URL 序列。"""

    queue: list[_FakeResponse] = []
    requests: list[str] = []

    def __init__(self, **kwargs: object) -> None:
        pass

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def stream(self, method: str, url: str) -> _FakeStream:
        type(self).requests.append(url)
        if not type(self).queue:
            raise AssertionError("no fake response queued")
        response = type(self).queue.pop(0)
        response.url = url
        return _FakeStream(response)


@pytest.fixture
def fake_client(monkeypatch: MonkeyPatch) -> type[_FakeClient]:
    _FakeClient.queue = []
    _FakeClient.requests = []
    monkeypatch.setattr(web_fetch_module.httpx, "Client", _FakeClient)
    return _FakeClient


def test_web_fetch_converts_html_to_markdown(fake_client: type[_FakeClient]) -> None:
    fake_client.queue = [
        _FakeResponse(
            200,
            content=(
                b"<html><body><h1>Title</h1>"
                b'<a href="/docs">Docs</a>'
                b"<script>bad()</script></body></html>"
            ),
            headers={"content-type": "text/html; charset=utf-8"},
        )
    ]

    result = web_fetch_module.web_fetch.invoke(
        {"url": "https://docs.example.com/page"}
    )

    assert "# Title" in result
    assert "[Docs](https://docs.example.com/docs)" in result
    assert "bad()" not in result


def test_web_fetch_returns_plain_text(fake_client: type[_FakeClient]) -> None:
    fake_client.queue = [
        _FakeResponse(
            200,
            content=b"raw text",
            headers={"content-type": "text/plain"},
        )
    ]

    result = web_fetch_module.web_fetch.invoke(
        {"url": "https://docs.example.com/raw"}
    )

    assert result == "raw text"


def test_web_fetch_follows_whitelisted_redirect(fake_client: type[_FakeClient]) -> None:
    fake_client.queue = [
        _FakeResponse(302, headers={"location": "/moved"}),
        _FakeResponse(
            200,
            content=b"<html><body>moved</body></html>",
            headers={"content-type": "text/html"},
        ),
    ]

    result = web_fetch_module.web_fetch.invoke(
        {"url": "https://docs.example.com/page"}
    )

    assert "moved" in result
    assert "redirected to https://docs.example.com/moved" in result
    assert fake_client.requests == [
        "https://docs.example.com/page",
        "https://docs.example.com/moved",
    ]


def test_web_fetch_blocks_redirect_outside_whitelist(
    fake_client: type[_FakeClient],
) -> None:
    fake_client.queue = [
        _FakeResponse(302, headers={"location": "https://evil.example.net/x"})
    ]

    result = web_fetch_module.web_fetch.invoke(
        {"url": "https://docs.example.com/page"}
    )

    assert result.startswith("Guardian 拦截")
    assert len(fake_client.requests) == 1  # 未请求重定向目标


def test_web_fetch_rejects_unsupported_content_type(
    fake_client: type[_FakeClient],
) -> None:
    fake_client.queue = [
        _FakeResponse(
            200, content=b"\x89PNG", headers={"content-type": "image/png"}
        )
    ]

    result = web_fetch_module.web_fetch.invoke(
        {"url": "https://docs.example.com/image.png"}
    )

    assert result == "不支持的内容类型：image/png"


def test_web_fetch_reports_http_error(fake_client: type[_FakeClient]) -> None:
    fake_client.queue = [_FakeResponse(500, headers={"content-type": "text/html"})]

    result = web_fetch_module.web_fetch.invoke(
        {"url": "https://docs.example.com/boom"}
    )

    assert result == "抓取失败：HTTP 500"


def test_web_fetch_truncates_long_content(fake_client: type[_FakeClient]) -> None:
    fake_client.queue = [
        _FakeResponse(
            200, content=b"x" * 5000, headers={"content-type": "text/plain"}
        )
    ]

    result = web_fetch_module.web_fetch.invoke(
        {"url": "https://docs.example.com/long", "max_chars": 1000}
    )

    assert "已截断" in result
    assert len(result) < 2000


def test_web_fetch_blocks_non_whitelisted_url(fake_client: type[_FakeClient]) -> None:
    result = web_fetch_module.web_fetch.invoke({"url": "https://evil.example.net"})

    assert result.startswith("Guardian 拦截")
    assert fake_client.requests == []
