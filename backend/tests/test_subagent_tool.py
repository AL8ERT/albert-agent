"""use_subagent 工具测试：子 agent 只把最终答案返回给主 agent。

用假模型 + 假子 agent 名单替换外部依赖，不访问真实模型或用户配置。
返回值为 ToolMessage：正文是最终答案，子 agent 用量合计挂在
additional_kwargs["subagent_usage"] 上供主流统计并入。
"""

import asyncio
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.prebuilt import ToolRuntime
from pytest import MonkeyPatch

from app.agents.prompts import build_subagent_system_prompt
from app.core.config import SubagentConfig
from app.core.usage import SUBAGENT_USAGE_KEY
from app.subagents import tool as subagent_tool
from app.tools.builtins import get_current_time

_DEFAULT_SUBAGENTS = [
    SubagentConfig(name="general", prompt="General tasks"),
]


def _fake_runtime() -> ToolRuntime:
    """直接 ainvoke 时手工构造的 ToolRuntime：只需 tool_call_id，其余占位。"""
    return ToolRuntime(
        state=None,
        context=None,
        config={},
        stream_writer=lambda chunk: None,
        tool_call_id="call-sub",
        store=None,
    )


class _NoopMiddleware(AgentMiddleware):
    """替换 SkillMiddleware，避免测试读取真实技能目录。"""


class _ScriptedModel(BaseChatModel):
    """按脚本依次返回 AI 消息，并记录模型看到的完整消息与绑定工具。"""

    replies: list[AIMessage] = []
    seen: list[list[Any]] = []
    bound: list[list[str]] = []
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_ScriptedModel":
        self.bound.append([getattr(item, "name", str(item)) for item in tools])
        return self

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=reply)])


class _BrokenModel(BaseChatModel):
    """模型调用直接失败，用于验证错误兜底。"""

    @property
    def _llm_type(self) -> str:
        return "broken"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_BrokenModel":
        return self

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise RuntimeError("model down")


def _patch_subagents(
    monkeypatch: MonkeyPatch,
    subagents: list[SubagentConfig] | None = None,
) -> None:
    monkeypatch.setattr(
        subagent_tool,
        "load_subagents",
        lambda: list(subagents if subagents is not None else _DEFAULT_SUBAGENTS),
    )
    monkeypatch.setattr(subagent_tool, "SkillMiddleware", _NoopMiddleware)


def test_use_subagent_returns_only_final_answer(monkeypatch: MonkeyPatch) -> None:
    """子 agent 内部有工具调用时，工具只返回最终答案文本与用量合计。"""
    model = _ScriptedModel(
        replies=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_current_time", "args": {}, "id": "call-1"}
                ],
                usage_metadata={
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            ),
            AIMessage(
                content="final answer",
                usage_metadata={
                    "input_tokens": 20,
                    "output_tokens": 5,
                    "total_tokens": 25,
                    "input_token_details": {"cached_tokens": 8},
                },
            ),
        ]
    )
    _patch_subagents(monkeypatch)
    use_subagent = subagent_tool.create_subagent_tool(
        model=model, tools=[get_current_time]
    )

    result = asyncio.run(
        use_subagent.ainvoke(
            {
                "agent_name": "general",
                "message": "do the task",
                "runtime": _fake_runtime(),
            }
        )
    )

    assert isinstance(result, ToolMessage)
    assert result.content == "final answer"
    assert result.tool_call_id == "call-sub"
    # 子 agent 两次模型调用的用量合计（第二次 20 扣除缓存 8 后为 12）
    assert result.additional_kwargs[SUBAGENT_USAGE_KEY] == {
        "input_tokens": 22,
        "output_tokens": 7,
        "total_tokens": 37,
        "cached_tokens": 8,
    }
    # 子 agent 使用传入的工具全集，且不含 use_subagent 自身
    assert model.bound
    assert all(names == ["get_current_time"] for names in model.bound)
    # 子 agent 的系统提示词 = 配置提示词 + 框架说明
    assert model.seen[0][0].content == build_subagent_system_prompt(
        "General tasks"
    )
    # 两次模型调用：工具调用 -> 最终答案
    assert model.calls == 2


def test_use_subagent_unknown_name_lists_available(
    monkeypatch: MonkeyPatch,
) -> None:
    model = _ScriptedModel(replies=[AIMessage(content="unused")])
    _patch_subagents(
        monkeypatch,
        [
            SubagentConfig(name="general", prompt="General tasks"),
            SubagentConfig(name="writer", prompt="Write prose"),
        ],
    )
    use_subagent = subagent_tool.create_subagent_tool(model=model, tools=[])

    result = asyncio.run(
        use_subagent.ainvoke(
            {
                "agent_name": "nope",
                "message": "hi",
                "runtime": _fake_runtime(),
            }
        )
    )

    assert isinstance(result, ToolMessage)
    assert "Unknown subagent 'nope'" in result.content
    assert "general" in result.content and "writer" in result.content
    # 未真正执行子 agent，不带用量
    assert SUBAGENT_USAGE_KEY not in result.additional_kwargs
    assert model.calls == 0


def test_use_subagent_reports_failure(monkeypatch: MonkeyPatch) -> None:
    """子 agent 执行失败时返回错误文本，不向上抛出异常。"""
    _patch_subagents(monkeypatch)
    use_subagent = subagent_tool.create_subagent_tool(
        model=_BrokenModel(), tools=[]
    )

    result = asyncio.run(
        use_subagent.ainvoke(
            {
                "agent_name": "general",
                "message": "hi",
                "runtime": _fake_runtime(),
            }
        )
    )

    assert isinstance(result, ToolMessage)
    assert result.content.startswith("Subagent 'general' failed: model down")
    assert result.tool_call_id == "call-sub"
