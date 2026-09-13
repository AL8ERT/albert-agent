"""Guardian 安全校验测试：read_file 路径、web_fetch URL 与中间件拦截。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.security import guard
from app.security.middleware import GuardianMiddleware


# ── read_file 路径校验 ──


def test_validate_read_path_allows_file_under_root(tmp_path: Path) -> None:
    target = tmp_path / "notes" / "a.txt"
    target.parent.mkdir()
    target.write_text("hello", encoding="utf-8")

    assert guard.validate_read_path(str(target), roots=[tmp_path]) == target.resolve()


def test_validate_read_path_rejects_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(guard.GuardError, match="目录范围"):
        guard.validate_read_path(str(outside), roots=[root])


def test_validate_read_path_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x", encoding="utf-8")

    with pytest.raises(guard.GuardError, match="目录范围"):
        guard.validate_read_path(str(root / ".." / "secret.txt"), roots=[root])


def test_validate_read_path_rejects_sensitive_files(tmp_path: Path) -> None:
    cases = [
        ".ssh/id_rsa",
        ".aws/credentials",
        ".env",
        "server.pem",
        "albert-agent-config.json",
        "id_ed25519",
    ]
    for relative in cases:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")

        with pytest.raises(guard.GuardError, match="拒绝访问"):
            guard.validate_read_path(str(target), roots=[tmp_path])


def test_validate_read_path_rejects_empty() -> None:
    with pytest.raises(guard.GuardError, match="路径为空"):
        guard.validate_read_path("  ")


def test_validate_read_path_rejects_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("当前环境不支持创建符号链接")

    with pytest.raises(guard.GuardError, match="目录范围"):
        guard.validate_read_path(str(link), roots=[root])


# ── web_fetch URL 校验 ──


def test_validate_fetch_url_allows_whitelisted_subdomain() -> None:
    url = "https://docs.example.com/page"

    assert guard.validate_fetch_url(url, domains=["example.com"]) == url


def test_validate_fetch_url_rejects_http() -> None:
    with pytest.raises(guard.GuardError, match="https"):
        guard.validate_fetch_url("http://example.com", domains=["example.com"])


def test_validate_fetch_url_rejects_non_whitelisted_domain() -> None:
    with pytest.raises(guard.GuardError, match="不在白名单"):
        guard.validate_fetch_url("https://evil.example.net", domains=["example.com"])


def test_validate_fetch_url_rejects_empty_whitelist() -> None:
    with pytest.raises(guard.GuardError, match="未配置"):
        guard.validate_fetch_url("https://example.com", domains=[])


def test_validate_fetch_url_rejects_localhost_and_ip() -> None:
    with pytest.raises(guard.GuardError, match="本机"):
        guard.validate_fetch_url("https://localhost/x", domains=["localhost"])
    with pytest.raises(guard.GuardError, match="IP"):
        guard.validate_fetch_url("https://127.0.0.1/x", domains=["127.0.0.1"])


def test_validate_fetch_url_rejects_userinfo_and_port() -> None:
    with pytest.raises(guard.GuardError, match="用户名/密码"):
        guard.validate_fetch_url("https://u:p@example.com", domains=["example.com"])
    with pytest.raises(guard.GuardError, match="443"):
        guard.validate_fetch_url("https://example.com:8443", domains=["example.com"])


def test_is_domain_allowed_matches_exact_and_subdomain() -> None:
    assert guard.is_domain_allowed("example.com", ["example.com"])
    assert guard.is_domain_allowed("a.b.example.com", ["example.com"])
    assert not guard.is_domain_allowed("notexample.com", ["example.com"])
    assert not guard.is_domain_allowed("example.com.evil.net", ["example.com"])


# ── GuardianMiddleware ──


def _tool_request(name: str, args: dict) -> SimpleNamespace:
    return SimpleNamespace(tool_call={"name": name, "args": args, "id": "call-1"})


def test_guardian_blocks_dangerous_read_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(guard, "_allowed_read_roots", lambda: [root])
    calls = 0

    def handler(request: object) -> str:
        nonlocal calls
        calls += 1
        return "executed"

    result = GuardianMiddleware().wrap_tool_call(
        _tool_request("read_file", {"path": str(tmp_path / "outside.txt")}), handler
    )

    assert calls == 0
    assert getattr(result, "status", None) == "error"
    assert str(result.content).startswith("Guardian 拦截")


def test_guardian_blocks_http_web_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "get_web_fetch_allowed_domains", lambda: ("example.com",))

    result = GuardianMiddleware().wrap_tool_call(
        _tool_request("web_fetch", {"url": "http://example.com"}), lambda req: "executed"
    )

    assert getattr(result, "status", None) == "error"
    assert "https" in str(result.content)


def test_guardian_allows_valid_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    target = root / "ok.txt"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr(guard, "_allowed_read_roots", lambda: [root])

    result = GuardianMiddleware().wrap_tool_call(
        _tool_request("read_file", {"path": str(target)}), lambda req: "executed"
    )

    assert result == "executed"


def test_guardian_ignores_unknown_tools() -> None:
    result = GuardianMiddleware().wrap_tool_call(
        _tool_request("some_mcp_tool", {"anything": "goes"}), lambda req: "executed"
    )

    assert result == "executed"
