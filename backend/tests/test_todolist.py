"""todolist 工具测试：整表替换语义、格式化输出与入参校验。"""

import pytest
from pydantic import ValidationError

from app.agents.assistant import filter_subagent_tools
from app.tools import get_builtin_tools
from app.tools.todolist import MAX_TODO_CONTENT_CHARS, MAX_TODO_ITEMS, todolist


def test_todolist_is_registered() -> None:
    """todolist 应出现在内置工具集合里。"""
    assert "todolist" in {tool.name for tool in get_builtin_tools()}


def test_todolist_docstring_carries_usage_rules() -> None:
    """工具描述应携带完整使用指引（何时用 / 何时不用 / 状态维护规则）。"""
    description = todolist.description

    assert "Full-replacement" in description
    assert "3 or more distinct steps" in description
    assert "When NOT to use" in description
    assert "only one item may be" in description
    assert "never batch completions" in description


def test_todolist_formats_items() -> None:
    """正常调用返回带优先级与状态中文标签的编号列表。"""
    result = todolist.invoke(
        {
            "todos": [
                {"content": "调研竞品", "priority": "high", "status": "in_progress"},
                {"content": "写报告", "priority": "medium", "status": "pending"},
            ]
        }
    )

    assert "共 2 项" in result
    assert "[高|进行中] 调研竞品" in result
    assert "[中|未开始] 写报告" in result


def test_todolist_empty_list_clears() -> None:
    """空列表表示清空待办事项。"""
    assert todolist.invoke({"todos": []}) == "已清空待办事项列表。"


def test_todolist_strips_content() -> None:
    """事项名去首尾空白后再展示。"""
    result = todolist.invoke(
        {"todos": [{"content": "  做事  ", "priority": "low", "status": "completed"}]}
    )

    assert "[低|已完成] 做事" in result


def test_todolist_truncates_long_content() -> None:
    """超长事项名截断到上限，避免撑爆上下文。"""
    result = todolist.invoke(
        {
            "todos": [
                {
                    "content": "长" * (MAX_TODO_CONTENT_CHARS + 10),
                    "priority": "low",
                    "status": "pending",
                }
            ]
        }
    )

    assert "长" * MAX_TODO_CONTENT_CHARS in result
    assert "长" * (MAX_TODO_CONTENT_CHARS + 1) not in result


def test_todolist_rejects_blank_content() -> None:
    """空白事项名属于非法输入，抛异常（ToolNode 会转成 error 结果）。"""
    with pytest.raises(ValueError, match="事项名为空"):
        todolist.invoke(
            {"todos": [{"content": "   ", "priority": "low", "status": "pending"}]}
        )


def test_todolist_rejects_too_many_items() -> None:
    """超过数量上限的列表直接拒绝。"""
    items = [
        {"content": f"事项{index}", "priority": "low", "status": "pending"}
        for index in range(MAX_TODO_ITEMS + 1)
    ]

    with pytest.raises(ValueError, match="最多"):
        todolist.invoke({"todos": items})


def test_todolist_rejects_invalid_enum() -> None:
    """优先级 / 状态不在枚举内时由 pydantic 拦截。"""
    with pytest.raises(ValidationError):
        todolist.invoke(
            {"todos": [{"content": "x", "priority": "urgent", "status": "pending"}]}
        )
    with pytest.raises(ValidationError):
        todolist.invoke(
            {"todos": [{"content": "x", "priority": "low", "status": "done"}]}
        )


def test_subagent_tools_exclude_todolist() -> None:
    """子 agent 不挂载 todolist（其调用不会反映到主线程的前端面板）。"""
    subagent_tools = filter_subagent_tools(get_builtin_tools())

    names = {tool.name for tool in subagent_tools}
    assert "todolist" not in names
    # 其余内置工具保持可用
    assert {"calculate", "web_search", "read_file"} <= names
