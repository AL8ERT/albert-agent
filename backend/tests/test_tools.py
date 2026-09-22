"""内置工具测试：时间格式化、时区容错、搜索结果文本化、文件读取与数学计算。"""

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
    """内置工具集合应包含计算、时间、搜索、读文件、抓网页与待办事项。"""
    assert {tool.name for tool in get_builtin_tools()} == {
        "calculate",
        "get_current_time",
        "web_search",
        "read_file",
        "web_fetch",
        "todolist",
    }


def test_calculate_basic_arithmetic() -> None:
    """四则运算与优先级：先乘除后加减。"""
    assert builtins.calculate.invoke({"expression": "2 + 3 * 4"}) == "2 + 3 * 4 = 14"


def test_calculate_parentheses_and_float() -> None:
    """括号改变优先级，除法产生浮点结果。"""
    result = builtins.calculate.invoke({"expression": "(1 + 2) / 4"})

    assert result == "(1 + 2) / 4 = 0.75"


def test_calculate_power_and_floor_div() -> None:
    assert builtins.calculate.invoke({"expression": "2 ** 10"}) == "2 ** 10 = 1024"
    assert builtins.calculate.invoke({"expression": "-7 // 2"}) == "-7 // 2 = -4"


def test_calculate_functions_and_constants() -> None:
    result = builtins.calculate.invoke({"expression": "floor(pi) + ceil(e)"})

    assert result == "floor(pi) + ceil(e) = 6"


def test_calculate_log_with_base() -> None:
    assert builtins.calculate.invoke({"expression": "log(8, 2)"}).endswith("= 3.0")


def test_calculate_rejects_division_by_zero() -> None:
    assert "计算失败" in builtins.calculate.invoke({"expression": "1 / 0"})


def test_calculate_rejects_invalid_syntax() -> None:
    assert "计算失败" in builtins.calculate.invoke({"expression": "2 +"})


def test_calculate_rejects_injection() -> None:
    """名称访问与函数调用都限定在白名单内，注入式表达式直接拒绝。"""
    assert (
        "计算失败"
        in builtins.calculate.invoke({"expression": "__import__('os').getcwd()"})
    )


def test_calculate_rejects_unknown_names_and_strings() -> None:
    assert "计算失败" in builtins.calculate.invoke({"expression": "x + 1"})
    assert "计算失败" in builtins.calculate.invoke({"expression": "'a' + 'b'"})


def test_calculate_rejects_huge_exponent() -> None:
    """链式幂 9**9**9 的外层指数超过上限，应在计算前被拦截。"""
    assert "计算失败" in builtins.calculate.invoke({"expression": "9 ** 9 ** 9"})


def test_calculate_rejects_empty_expression() -> None:
    assert "计算失败" in builtins.calculate.invoke({"expression": "   "})


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
