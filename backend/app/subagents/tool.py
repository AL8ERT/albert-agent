"""子 agent 工具：use_subagent。

主 agent 通过该工具按名称调用子 agent：子 agent 拥有全部技能与工具权限，
在自己的消息历史里完成执行；工具只把子 agent 的最终答案作为返回值交给主
agent 的模型，中间工具调用等信息不会回流到主 agent 的上下文。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool

from app.agents.prompts import build_subagent_system_prompt
from app.core.config import SubagentConfig
from app.core.messages import extract_text
from app.security.middleware import GuardianMiddleware
from app.skills.middleware import SkillMiddleware
from app.subagents.loader import load_subagents

logger = logging.getLogger(__name__)


def build_subagent_graph(
    model: BaseChatModel,
    tools: list[BaseTool],
    subagent: SubagentConfig,
) -> Any:
    """构建单个子 agent 图：拥有全部工具与技能，但不能再调用子 agent。"""
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=build_subagent_system_prompt(subagent.prompt),
        middleware=[GuardianMiddleware(), SkillMiddleware()],
    )


def _final_answer(messages: list[Any]) -> str:
    """取最后一条 AI 消息的文本作为子 agent 的最终答案。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = extract_text(message.content)
            if text:
                return text
    return ""


def create_subagent_tool(model: BaseChatModel, tools: list[BaseTool]) -> BaseTool:
    """创建 use_subagent 工具。

    子 agent 图在首次调用时构建并按名称缓存；tools 为子 agent 可用的工具
    全集（不含 use_subagent 本身，避免无限递归）。
    """
    graphs: dict[str, Any] = {}

    def _graph_for(subagent: SubagentConfig) -> Any:
        """按名称取缓存的子 agent 图，首次调用时才构建（懒加载）。"""
        graph = graphs.get(subagent.name)
        if graph is None:
            graph = build_subagent_graph(model, tools, subagent)
            graphs[subagent.name] = graph
        return graph

    @tool
    async def use_subagent(agent_name: str, message: str) -> str:
        """Delegate a task to a subagent and return its final answer.

        The subagent runs with the same skills and tools, but cannot see this
        conversation, so pass every detail it needs. Only the subagent's final
        answer comes back; its intermediate steps stay hidden.

        Args:
            agent_name: Name of the subagent to call, exactly as listed in
                <available_subagents>.
            message: Complete task description with all required context.
        """
        try:
            subagents = load_subagents()
            subagent = next(
                (item for item in subagents if item.name == agent_name), None
            )
            if subagent is None:
                available = ", ".join(item.name for item in subagents) or "none"
                return (
                    f"Unknown subagent {agent_name!r}. "
                    f"Available subagents: {available}."
                )
            result = await _graph_for(subagent).ainvoke(
                {"messages": [HumanMessage(content=message)]}
            )
        except Exception as exc:
            logger.exception("Subagent %r failed", agent_name)
            return f"Subagent {agent_name!r} failed: {exc}"

        answer = _final_answer(result.get("messages", []))
        return answer or f"Subagent {agent_name!r} returned no answer."

    return use_subagent
