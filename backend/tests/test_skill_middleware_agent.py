"""技能中间件的端到端行为：用假模型 + InMemorySaver 跑真实 create_agent 图。

验证三点：
1. 首轮把完整技能清单作为隐藏 HumanMessage 追加（模型能看到、state 持久化）；
2. 系统提示词保持静态，不带技能段；
3. 次轮新增/删除技能以隐藏 HumanMessage 追加，且持久化在 checkpointer 中。
"""

import asyncio
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import SubagentConfig
from app.skills.loader import SkillMetadata
from app.skills.middleware import SkillMiddleware
from app.subagents.middleware import SubagentMiddleware


class _RecordingFakeModel(BaseChatModel):
    """记录每次模型调用收到的完整消息列表，并返回固定文本。"""

    replies: list[str] = ["ok"]
    seen: list[list[Any]] = []
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_RecordingFakeModel":
        return self

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen.append(list(messages))
        index = min(self.calls, len(self.replies) - 1)
        self.calls += 1
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.replies[index]))]
        )


def test_skill_middleware_first_and_second_turn() -> None:
    skills = [SkillMetadata(name="pdf", description="PDF", path="/s/pdf/SKILL.md")]
    current: dict[str, list[SkillMetadata]] = {"values": skills}
    model = _RecordingFakeModel()
    agent = create_agent(
        model=model,
        tools=[],
        system_prompt="base prompt",
        middleware=[SkillMiddleware(loader=lambda: current["values"])],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "t1"}}

    async def run() -> tuple[dict, dict]:
        await agent.ainvoke({"messages": [HumanMessage(content="hello")]}, config)
        state_after_first = await agent.aget_state(config)
        # 用户新增了一个技能后继续对话
        current["values"] = [
            *skills,
            SkillMetadata(name="new", description="N", path="/s/new/SKILL.md"),
        ]
        await agent.ainvoke({"messages": [HumanMessage(content="again")]}, config)
        state_after_second = await agent.aget_state(config)
        return state_after_first.values, state_after_second.values

    first_state, second_state = asyncio.run(run())

    # 首轮模型看到完整技能清单（隐藏 HumanMessage 在 state 里）
    assert first_state["announced_skills"] == ["pdf"]
    assert any(
        message.additional_kwargs.get("hide_from_chat")
        and "<available_skills>" in message.content
        for message in first_state["messages"]
    )
    # 系统提示词始终静态，不包含技能段
    assert "<available_skills>" not in model.seen[0][0].content
    assert "<available_skills>" not in model.seen[-1][0].content

    # 次轮追加了隐藏的差分消息，且它持久化在 checkpointer 里
    hidden = [
        message
        for message in second_state["messages"]
        if message.additional_kwargs.get("hide_from_chat")
    ]
    assert len(hidden) == 2
    assert "<skill_update>" in hidden[-1].content
    assert "new" in hidden[-1].content
    assert second_state["announced_skills"] == ["new", "pdf"]


def test_skill_and_subagent_middleware_coexist() -> None:
    """两个中间件同时挂载时 state schema 合并，各自注入隐藏消息。"""
    model = _RecordingFakeModel()
    agent = create_agent(
        model=model,
        tools=[],
        system_prompt="base prompt",
        middleware=[
            SkillMiddleware(loader=lambda: []),
            SubagentMiddleware(
                loader=lambda: [
                    SubagentConfig(name="general", prompt="General tasks")
                ]
            ),
        ],
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "t1"}}

    async def run() -> dict:
        await agent.ainvoke({"messages": [HumanMessage(content="hello")]}, config)
        state = await agent.aget_state(config)
        return state.values

    values = asyncio.run(run())

    assert values["announced_skills"] == []
    assert values["announced_subagents"] == ["general"]
    assert any(
        message.additional_kwargs.get("hide_from_chat")
        and "<available_subagents>" in message.content
        for message in values["messages"]
    )
