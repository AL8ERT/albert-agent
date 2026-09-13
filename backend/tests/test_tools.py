"""内置工具测试：时间格式化、时区容错、搜索结果文本化与文件读取。"""

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app.security import guard
from app.tools import builtins, get_builtin_tools


@pytest.fixture(autouse=True)
def _allow_tmp_reads(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """read_file 的路径校验默认只放行家目录/工作目录，测试把根目录指向 tmp。"""
    monkeypatch.setattr(guard, "_allowed_read_roots", lambda: [tmp_path])


def test_builtin_tools_are_registered() -> None:
    """内置工具集合应包含时间、搜索、读文件与抓网页。"""
    assert {tool.name for tool in get_builtin_tools()} == {
        "get_current_time",
        "web_search",
        "read_file",
        "web_fetch",
    }


def test_get_current_time_formats_utc() -> None:
    result = builtins.get_current_time.invoke({"timezone": "UTC"})

    assert isinstance(result, str)
    assert "UTC" in result


def test_get_current_time_rejects_unknown_timezone() -> None:
    result = builtins.get_current_time.invoke({"timezone": "Not/AZone"})

    assert result == "未知时区：Not/AZone"


class _FakeDDGS:
    """DDGS 替身：固定返回一条搜索结果，避免测试访问网络。"""

    def text(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        return [
            {
                "title": "Example",
                "href": "https://example.com",
                "body": "some snippet",
            }
        ]


def test_web_search_formats_results(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "DDGS", _FakeDDGS)

    result = builtins.web_search.invoke({"query": "hello"})

    assert "1. Example" in result
    assert "https://example.com" in result
    assert "some snippet" in result


def test_web_search_reports_failure(monkeypatch: MonkeyPatch) -> None:
    class _BrokenDDGS:
        def text(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
            raise RuntimeError("network down")

    monkeypatch.setattr(builtins, "DDGS", _BrokenDDGS)

    result = builtins.web_search.invoke({"query": "hello"})

    assert result.startswith("搜索失败")


def test_read_file_reads_text(tmp_path: Path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("line1\nline2\n", encoding="utf-8")

    assert builtins.read_file.invoke({"path": str(path)}) == "line1\nline2"


def test_read_file_supports_offset_and_limit(tmp_path: Path) -> None:
    path = tmp_path / "many.txt"
    path.write_text("\n".join(f"L{index}" for index in range(10)), encoding="utf-8")

    result = builtins.read_file.invoke({"path": str(path), "offset": 2, "limit": 3})

    assert result.startswith("L2\nL3\nL4")
    assert "还有 5 行未显示" in result


def test_read_file_missing_and_binary(tmp_path: Path) -> None:
    missing = builtins.read_file.invoke({"path": str(tmp_path / "nope.txt")})
    assert "不存在" in missing

    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02")
    assert "二进制" in builtins.read_file.invoke({"path": str(binary)})


def test_read_file_rejects_oversized(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    path = tmp_path / "big.txt"
    path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(builtins, "MAX_READ_BYTES", 0)

    assert "文件过大" in builtins.read_file.invoke({"path": str(path)})
