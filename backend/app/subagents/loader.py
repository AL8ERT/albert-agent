"""子 agent 加载与渲染：读取应用配置里的子 agent，并生成注入用文本。

子 agent 定义在应用配置的 ``subagents`` 数组里（每项 name + prompt），
系统内置一个 general 通用任务子 agent。本模块只负责取快照与渲染；
注入时机由 app.subagents.middleware 控制。
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable

from app.core.config import SubagentConfig, get_subagents

SubagentLoader = Callable[[], list[SubagentConfig]]


def load_subagents() -> list[SubagentConfig]:
    """返回当前生效的子 agent 列表（用户配置 + 内置默认）。"""
    return list(get_subagents())


def _escape(value: str) -> str:
    """转义 XML 尖括号，防止名称/提示词伪造框架标签。"""
    return html.escape(value, quote=False)


def _format_subagent_line(subagent: SubagentConfig) -> str:
    prompt = " ".join(subagent.prompt.split())
    return f"- {_escape(subagent.name)}: {_escape(prompt)}"


def render_subagents_section(subagents: Iterable[SubagentConfig]) -> str:
    """渲染首轮注入的 <available_subagents> 段。"""
    items = list(subagents)
    if not items:
        return ""
    lines = ["<available_subagents>"]
    lines.extend(_format_subagent_line(subagent) for subagent in items)
    lines.append("</available_subagents>")
    return "\n".join(lines)


def render_subagent_update(
    added: Iterable[SubagentConfig], removed: Iterable[str]
) -> str:
    """渲染后续轮次注入消息尾部的 <subagent_update> 段（只含增删差分）。"""
    added_items = list(added)
    removed_items = list(removed)
    lines = ["<subagent_update>"]
    if added_items:
        lines.append("Added subagents:")
        lines.extend(_format_subagent_line(subagent) for subagent in added_items)
    if removed_items:
        lines.append("Removed subagents:")
        lines.extend(f"- {_escape(name)}" for name in removed_items)
    lines.append("</subagent_update>")
    return "\n".join(lines)
