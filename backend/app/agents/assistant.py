"""Agent 工厂：按模型名创建 LangChain agent，并挂载统一的 checkpointer。

- 工具 = 内置工具（当前时间、网页搜索等）+ 启动时加载的 MCP 工具 + use_subagent；
- SkillMiddleware 负责技能元数据注入（首轮全量隐藏消息，后续轮次注入增删差分）；
- SubagentMiddleware 注入可用子 agent 名单，use_subagent 工具按名称调用子 agent；
- checkpointer 由 app.core.database 提供（PostgreSQL 或内存），所有模型共享同一实例，
  会话之间通过 config 里的 thread_id 隔离。
"""

from functools import lru_cache
from typing import Any

from langchain.agents import create_agent

from app.agents.chat_model import ReasoningChatOpenAI

from app.agents.prompts import build_system_prompt
from app.core.config import find_model, get_settings
from app.core.database import get_checkpointer
from app.mcp.manager import get_mcp_tools
from app.security.middleware import GuardianMiddleware
from app.skills.middleware import SkillMiddleware
from app.subagents.middleware import SubagentMiddleware
from app.subagents.tool import create_subagent_tool
from app.tools import get_builtin_tools

__all__ = ["build_system_prompt", "get_agent"]


@lru_cache
def get_agent(model_name: str) -> Any:
    """按模型名构建并缓存 agent。

    模型未配置或缺少 API Key 时抛 RuntimeError，由上层转成 SSE error 事件。
    MCP 工具来自启动时的进程内缓存；修改 MCP / 子 agent 配置后需重启后端。
    """
    model_config = find_model(model_name)
    if model_config is None:
        raise RuntimeError(f"Model {model_name!r} is not configured.")
    if not model_config.api_key:
        raise RuntimeError(f"No API key configured for model {model_name!r}.")

    settings = get_settings()
    # 兼容 OpenAI 协议的服务（DeepSeek 等）统一用 ChatOpenAI + 自定义 base_url；
    # ReasoningChatOpenAI 在其基础上保留第三方 provider 的 reasoning_content
    # （思维链增量），供 SSE 层以 reasoning 事件推送给前端
    model = ReasoningChatOpenAI(
        model=model_config.name,
        api_key=model_config.api_key,
        base_url=model_config.base_url,
        temperature=settings.llm_temperature,
        streaming=True,  # 必须开启流式，SSE 才能逐 token 推送
        # 自定义 base_url 时 langchain-openai 默认不带 stream_options.include_usage，
        # 显式开启后每次模型调用的最终 chunk 会携带 usage_metadata（含缓存命中）
        stream_usage=True,
    )
    # 子 agent 复用主 agent 的模型与全部常规工具，但不挂 use_subagent（避免递归）
    base_tools = [*get_builtin_tools(), *get_mcp_tools()]
    # system_prompt 由 create_agent 在调用模型时注入，不写入 checkpoint；
    # checkpointer 负责多轮对话的历史持久化，按 config.configurable.thread_id 隔离。
    return create_agent(
        model=model,
        tools=[*base_tools, create_subagent_tool(model=model, tools=base_tools)],
        system_prompt=build_system_prompt(),
        middleware=[
            GuardianMiddleware(),
            SkillMiddleware(),
            SubagentMiddleware(),
        ],
        checkpointer=get_checkpointer(),
    )
