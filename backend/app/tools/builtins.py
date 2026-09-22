"""内置工具：当前时间、网页搜索、文件读取与数学计算。

这些工具与 MCP 工具一样直接挂到 create_agent 的 tools 列表里；
网页搜索走 DuckDuckGo（ddgs），无需 API Key。
"""

from __future__ import annotations

import ast
import logging
import math
import operator
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ddgs import DDGS
from langchain_core.tools import tool

from app.security.guard import GuardError, validate_read_path

logger = logging.getLogger(__name__)

# 单次读取上限：超过则拒绝，避免把大文件/二进制塞进上下文
MAX_READ_BYTES = 2_000_000
MAX_READ_LINES = 2000

# 数学表达式安全求值的上限：防超长输入与超大幂运算阻塞进程
MAX_EXPRESSION_LENGTH = 1000
MAX_EXPONENT = 10_000  # ** 指数绝对值上限（9**9**9 这类链式幂会被此规则拦截）
MAX_RESULT_BITS = 40_000  # 整数结果位数上限（约 1.2 万位十进制）


_CALC_BINOPS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CALC_UNARYOPS: dict[type, Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_CALC_FUNCTIONS: dict[str, Callable] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "pow": pow,
    "sqrt": math.sqrt,
    "cbrt": math.cbrt,
    "exp": math.exp,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": math.factorial,
}
_CALC_CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _eval_calc_node(node: ast.AST) -> int | float:
    """递归求值 AST 节点：只放行白名单内的运算符、函数与常量。

    任何其他节点（属性访问、字符串、下标、lambda 等）都会抛 ValueError，
    因此 `__import__`、`os.system` 之类的注入无法通过。
    """
    if isinstance(node, ast.Expression):
        return _eval_calc_node(node.body)
    if isinstance(node, ast.Constant):
        # bool 是 int 的子类，需显式排除；字符串/None 等一律拒绝
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("只允许数字常量")
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_BINOPS:
        left = _eval_calc_node(node.left)
        right = _eval_calc_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError(f"指数绝对值超过 {MAX_EXPONENT}，拒绝计算")
        return _CALC_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_UNARYOPS:
        return _CALC_UNARYOPS[type(node.op)](_eval_calc_node(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _CALC_FUNCTIONS
    ):
        if node.keywords:
            raise ValueError("不支持关键字参数")
        args = [_eval_calc_node(arg) for arg in node.args]
        return _CALC_FUNCTIONS[node.func.id](*args)
    if isinstance(node, ast.Name) and node.id in _CALC_CONSTANTS:
        return _CALC_CONSTANTS[node.id]
    raise ValueError("不支持的表达式元素")


# 工具描述译文（模型看到的是英文，此注释供维护者对照）：
# 计算数学表达式并返回结果（精确计算请优先使用本工具，不要心算）。
# 支持：四则运算 + - * /、整除 //、取余 %、乘方 **、括号、一元正负号；
# 函数 sqrt/cbrt/exp/log/log2/log10/sin/cos/tan/asin/acos/atan/sinh/cosh/tanh/
# floor/ceil/abs/round/min/max/pow/factorial；常量 pi/e/tau。
# 幂运算写 **（不是 ^）。log 默认自然对数，可传底数如 log(8, 2)。
# 参数 expression：数学表达式，如 "(1 + 2) * 3 ** 2"、"sqrt(16) + pi"。
@tool
def calculate(expression: str) -> str:
    """Evaluate a math expression and return the result (prefer this tool for
    exact arithmetic; do not compute in your head).

    Supports: arithmetic + - * /, floor division //, modulo %, power **,
    parentheses, unary plus/minus; functions sqrt/cbrt/exp/log/log2/log10/
    sin/cos/tan/asin/acos/atan/sinh/cosh/tanh/floor/ceil/abs/round/min/max/
    pow/factorial; constants pi/e/tau. Use ** for exponentiation (not ^).
    log is the natural logarithm by default and accepts a base, e.g.
    log(8, 2).

    Args:
        expression: The math expression, e.g. "(1 + 2) * 3 ** 2" or
            "sqrt(16) + pi".
    """
    expression = expression.strip()
    if not expression or len(expression) > MAX_EXPRESSION_LENGTH:
        return f"计算失败：表达式为空或超过 {MAX_EXPRESSION_LENGTH} 字符"
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_calc_node(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as exc:
        return f"计算失败：{exc}"
    if isinstance(result, complex):
        return "计算失败：结果为复数"
    if isinstance(result, float) and (math.isinf(result) or math.isnan(result)):
        return "计算失败：结果超出可表示范围"
    if isinstance(result, int) and result.bit_length() > MAX_RESULT_BITS:
        return f"计算失败：整数结果超过 {MAX_RESULT_BITS} 个二进制位"
    return f"{expression} = {result}"


# 工具描述译文：获取当前日期和时间。参数 timezone：可选 IANA 时区名
# （如 Asia/Shanghai、America/New_York），缺省使用运行环境的本地时区。
@tool
def get_current_time(timezone: str | None = None) -> str:
    """Get the current date and time.

    Args:
        timezone: Optional IANA timezone name (e.g. Asia/Shanghai,
            America/New_York); defaults to the local timezone of the runtime.
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


# 工具描述译文：搜索互联网，返回若干条网页的标题、链接与摘要。
# 参数 query：搜索关键词；max_results：返回结果条数（1-10，默认 5）。
@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the internet and return titles, links and snippets of web pages.

    Args:
        query: The search keywords.
        max_results: Number of results to return (1-10, default 5).
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


# 工具描述译文：读取文本文件内容（用于查看 SKILL.md、配置文件、代码等）。
# 参数 path：文件路径，支持 ~ 展开；offset：起始行号（从 0 开始，默认 0）；
# limit：最多返回的行数（默认 2000）。
@tool
def read_file(path: str, offset: int = 0, limit: int = MAX_READ_LINES) -> str:
    """Read the content of a text file (for viewing SKILL.md, config files,
    code, etc.).

    Args:
        path: The file path; ~ expansion is supported.
        offset: Starting line number (0-based, default 0).
        limit: Maximum number of lines to return (default 2000).
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
