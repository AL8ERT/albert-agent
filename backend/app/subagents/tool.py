"""子 agent 工具：use_subagent。

主 agent 通过该工具按名称调用子 agent：子 agent 拥有全部技能与工具权限，
在自己的消息历史里完成执行；工具只把子 agent 的最终答案作为返回值交给主
agent 的模型，中间工具调用等信息不会回流到主 agent 的上下文。

token 统计例外：子 agent 全部用量合计写入返回 ToolMessage 的
additional_kwargs["subagent_usage"]（见 app.core.usage），随 checkpointer
持久化，主流的 turn_usage / total_usage 会把它并入总数。
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, InjectedToolArg, tool
from langgraph.prebuilt import ToolRuntime

from app.agents.prompts import build_subagent_system_prompt
from app.core.config import SubagentConfig
from app.core.messages import extract_text
from app.core.usage import SUBAGENT_USAGE_KEY, messages_usage
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
    async def use_subagent(
        agent_name: str,
        message: str,
        # 框架注入的运行时信息：InjectedToolArg 标注后不会暴露给模型的工具 schema，
        # ToolNode 执行时自动填入，从这里拿到本次调用的 tool_call_id。
        # 注意不能直接注入名为 tool_call_id 的字符串参数（该版本不会自动注入，
        # 会报 "tool_call_id: Field required"）。
        runtime: Annotated[ToolRuntime, InjectedToolArg()],
    ) -> ToolMessage:
        # 工具描述译文（模型看到的是英文，此注释供维护者对照）：
        # 把任务委派给子 agent 并返回其最终答案。子 agent 拥有相同的技能与工具，
        # 但看不到当前对话，所以要把所需的全部细节都写进任务描述里；只有子 agent
        # 的最终答案会返回，其内部中间步骤保持隐藏。
        # 参数 agent_name：要调用的子 agent 名称，与 <available_subagents> 中
        # 列出的完全一致；message：包含全部所需上下文的完整任务描述。
        """Delegate a task to a subagent and return its final answer.

        The subagent runs with the same skills and tools, but cannot see this
        conversation, so pass every detail it needs. Only the subagent's final
        answer comes back; its intermediate steps stay hidden.

        Args:
            agent_name: Name of the subagent to call, exactly as listed in
                <available_subagents>.
            message: Complete task description with all required context.
        """
        # 工具直接返回 ToolMessage（而非纯文本）：一是把 tool_call_id 关联上，
        # 二是能把子 agent 用量合计挂到 additional_kwargs 随消息持久化。
        # ToolNode 对 ToolMessage 返回值原样透传，不会重建。
        try:
            subagents = load_subagents()
            subagent = next(
                (item for item in subagents if item.name == agent_name), None
            )
            if subagent is None:
                # 名单里找不到：返回可用名单提示模型改用正确的名称（未执行，无用量）
                available = ", ".join(item.name for item in subagents) or "none"
                return ToolMessage(
                    content=(
                        f"Unknown subagent {agent_name!r}. "
                        f"Available subagents: {available}."
                    ),
                    tool_call_id=runtime.tool_call_id,
                    name="use_subagent",
                )
            # 起止日志：卡住时后端窗口停在 start 且迟迟没有 done，
            # 可据此判断问题出在子 agent 内部（模型调用或其工具）
            logger.info("use_subagent start: agent=%s", agent_name)
            started = time.perf_counter()
            result = await _graph_for(subagent).ainvoke(
                {"messages": [HumanMessage(content=message)]}
            )
            logger.info(
                "use_subagent done: agent=%s elapsed=%.1fs",
                agent_name,
                time.perf_counter() - started,
            )
        except Exception as exc:
            # 异常不向上抛：转成错误 ToolMessage 交回主 agent 自行决定下一步；
            # 此处拿不到子 agent 的消息列表，用量无法统计（该次不计入）
            logger.exception("Subagent %r failed", agent_name)
            return ToolMessage(
                content=f"Subagent {agent_name!r} failed: {exc}",
                tool_call_id=runtime.tool_call_id,
                name="use_subagent",
            )

        subagent_messages = result.get("messages", [])
        answer = _final_answer(subagent_messages)
        # 子 agent 用量合计（其全部模型调用之和）随 ToolMessage 进入主线程
        # state，主流的 turn_usage / total_usage 统计时并入总数
        usage = messages_usage(subagent_messages)
        additional = (
            {SUBAGENT_USAGE_KEY: usage.model_dump()} if usage is not None else {}
        )
        # name 需显式设置：ToolNode 对 ToolMessage 返回值不会自动补工具名，
        # 缺失会导致前端工具卡片与 SSE tool_result 事件拿不到 name
        return ToolMessage(
            content=answer or f"Subagent {agent_name!r} returned no answer.",
            tool_call_id=runtime.tool_call_id,
            name="use_subagent",
            additional_kwargs=additional,
        )

    return use_subagent
