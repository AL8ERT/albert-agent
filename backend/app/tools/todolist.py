"""待办事项工具：todolist。

主 agent 在处理复杂 / 多步任务时用它规划与跟踪进度。整表替换语义：
每次调用传入当前完整列表（不是增量），前端根据最新一次成功调用的
入参渲染常驻的待办面板（复用 tool_call / tool_result 事件，无独立状态）。
"""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

# 列表规模与单条长度上限：防止模型生成的超长列表撑爆上下文
MAX_TODO_ITEMS = 50
MAX_TODO_CONTENT_CHARS = 200

_PRIORITY_LABELS = {"low": "低", "medium": "中", "high": "高"}
_STATUS_LABELS = {
    "pending": "未开始",
    "in_progress": "进行中",
    "completed": "已完成",
    "abandoned": "已放弃",
}


class TodoItem(BaseModel):
    """单个待办事项。"""

    # 译文：事项名，一句话说明这一步要做什么
    content: str = Field(description="What this step does, in one short sentence")
    # 译文：优先级：low 低 / medium 中 / high 高
    priority: Literal["low", "medium", "high"] = Field(
        description="Priority: low / medium / high"
    )
    # 译文：状态：pending 未开始 / in_progress 进行中 / completed 已完成 /
    # abandoned 已放弃
    status: Literal["pending", "in_progress", "completed", "abandoned"] = Field(
        description="Status: pending (not started) / in_progress / completed / "
        "abandoned (dropped)"
    )


# 工具描述译文（模型看到的是英文，此注释供维护者对照）：
# 创建或更新待办事项列表：复杂任务的结构化工作看板，向用户展示进度。
# 整表替换语义：每次调用传入当前完整列表（不是只传新增或变化项），传空列表
# 表示清空。
# 何时使用（主动使用）：任务需要 3 个及以上独立步骤（不是同一个概念步骤的
# 多次工具调用）；工作不简单、能从规划中受益；用户一次性给出多个任务（编号
# 或逗号分隔）、或明确要求用待办列表；有新指令到达时，把它们记为新的待办
# 事项；开始做某项前，先把它标为 in_progress（同一时间只能有一项进行中）；
# 工作真正做完（包括必要的验证）后才标为 completed，绝不要凭意图就批量标记
# 完成；被阻塞或只完成一部分的事项保持 in_progress，并追加一条描述阻塞原因
# 的后续待办。
# 何时不用：单个简单任务（或不足 3 个琐碎步骤）；纯咨询 / 交流性质的请求；
# 跟踪不会带来组织价值。
@tool
def todolist(todos: list[TodoItem]) -> str:
    """Create or update the todo list: a structured work board for complex tasks,
    showing progress to the user.

    Full-replacement semantics: every call passes the complete current list
    (not just new or changed items); an empty list clears it.

    When to use (proactively):
    - The task requires 3 or more distinct steps (not several tool calls for
      one conceptual step);
    - The work is non-trivial and benefits from planning;
    - The user provides multiple tasks (numbered or comma-separated), or
      explicitly asks for a todo list;
    - New instructions arrive — capture them as new todo items;
    - Before starting an item, mark it in_progress (only one item may be
      in_progress at a time);
    - Mark an item completed only after the work is actually done, including
      any required verification — never batch completions based on intent
      alone;
    - When blocked or partial, keep the item in_progress and append a
      follow-up item describing the blocker.

    When NOT to use:
    - A single straightforward task (or fewer than 3 trivial steps);
    - Purely informational or conversational requests;
    - Tracking adds no organizational value.

    Args:
        todos: Array of all current todo items, each with content, priority
            and status.
    """
    # 结构非法时抛异常（ToolNode 会转成 error 结果），前端只提交成功
    # 结果对应的列表，避免把无效状态渲染进常驻面板
    if len(todos) > MAX_TODO_ITEMS:
        raise ValueError(f"待办事项最多 {MAX_TODO_ITEMS} 项，当前 {len(todos)} 项")

    normalized: list[TodoItem] = []
    for index, item in enumerate(todos, start=1):
        content = item.content.strip()
        if not content:
            raise ValueError(f"第 {index} 项事项名为空")
        normalized.append(
            TodoItem(
                content=content[:MAX_TODO_CONTENT_CHARS],
                priority=item.priority,
                status=item.status,
            )
        )

    if not normalized:
        return "已清空待办事项列表。"

    lines = [f"待办事项已更新（共 {len(normalized)} 项）："]
    for index, item in enumerate(normalized, start=1):
        lines.append(
            f"{index}. [{_PRIORITY_LABELS[item.priority]}|"
            f"{_STATUS_LABELS[item.status]}] {item.content}"
        )
    return "\n".join(lines)
