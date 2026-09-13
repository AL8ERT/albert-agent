"""对话服务单元测试：SSE 错误处理、消息序列化与 run 审计写入。

全部通过假 agent / 假存储替换外部依赖，不访问真实模型或数据库。
"""

import asyncio
import json
from typing import Any

from langchain.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    ToolMessage,
)
from pytest import MonkeyPatch

from app.schemas.chat import ThreadMessage
from app.services import chat_service


def test_stream_reports_agent_error(monkeypatch: MonkeyPatch) -> None:
    """agent 构建失败时，应把异常转成 error 事件，并以 done 事件收尾。"""
    # get_agent 抛错即模拟模型未配置 / API Key 缺失
    def broken_agent(model_name: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_service, "get_agent", broken_agent)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in chat_service.stream_chat_reply("hi", "test-model")
        ]

    chunks = asyncio.run(collect())

    assert chunks[0] == 'data: {"type":"error","message":"boom"}\n\n'
    assert chunks[-1] == 'data: {"type":"done"}\n\n'


class _StreamAgent:
    """按预设的 (mode, payload) 步骤产出 astream 的 agent 替身。"""

    def __init__(self, steps: list[tuple[str, Any]]) -> None:
        self.steps = steps

    async def astream(self, *args: Any, **kwargs: Any):
        for step in self.steps:
            yield step

    async def aget_state(self, config: dict[str, Any]) -> None:
        return None


def test_stream_emits_intermediate_text_and_tool_events(
    monkeypatch: MonkeyPatch,
) -> None:
    """LLM 中间文本、工具调用与工具结果都应转成对应的 SSE 事件。

    - messages 模式的增量文本 -> token（带 message_id，便于前端归组）；
    - updates 模式的 AI 消息 tool_calls -> tool_call；
    - updates 模式的 ToolMessage -> tool_result；
    - 隐藏消息（框架注入）与纯文本 AI 消息不重复产生事件。
    """
    hidden = HumanMessage(
        content="<available_skills>",
        additional_kwargs={"hide_from_chat": True},
    )
    first_ai = AIMessage(
        content="Let me search.",
        id="ai-1",
        tool_calls=[
            {"name": "web_search", "args": {"query": "x"}, "id": "call-1"}
        ],
    )
    tool_message = ToolMessage(
        content="search result", tool_call_id="call-1", name="web_search"
    )
    final_ai = AIMessage(content="Done", id="ai-2")
    agent = _StreamAgent(
        [
            # 不支持原生流式的模型在 messages 模式回退为完整 AIMessage
            ("messages", (AIMessage(content="non-streamed ", id="ai-0"), {})),
            ("messages", (AIMessageChunk(content="Let me ", id="ai-1"), {})),
            ("messages", (AIMessageChunk(content="search.", id="ai-1"), {})),
            ("updates", {"model": {"messages": [hidden, first_ai]}}),
            ("updates", {"tools": {"messages": [tool_message]}}),
            ("messages", (AIMessageChunk(content="Done", id="ai-2"), {})),
            ("updates", {"model": {"messages": [final_ai]}}),
        ]
    )
    monkeypatch.setattr(
        chat_service, "get_agent", lambda model_name: agent
    )

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in chat_service.stream_chat_reply("hi", "test-model")
        ]

    raw_chunks = asyncio.run(collect())
    events = [
        json.loads(chunk.removeprefix("data: ").strip()) for chunk in raw_chunks
    ]

    assert events == [
        {"type": "token", "content": "non-streamed ", "message_id": "ai-0"},
        {"type": "token", "content": "Let me ", "message_id": "ai-1"},
        {"type": "token", "content": "search.", "message_id": "ai-1"},
        {
            "type": "tool_call",
            "tool_call_id": "call-1",
            "name": "web_search",
            "args": {"query": "x"},
            "message_id": "ai-1",
        },
        {
            "type": "tool_result",
            "tool_call_id": "call-1",
            "name": "web_search",
            "content": "search result",
            "status": "success",
        },
        {"type": "token", "content": "Done", "message_id": "ai-2"},
        {"type": "done"},
    ]


class _FakeState:
    """模拟 langgraph 的 StateSnapshot：只需要 values.messages。"""

    values = {
        "messages": [
            HumanMessage(content="hi"),
            # 列表形式的内容块，用于覆盖 extract_text 的拼接逻辑
            AIMessage(content=[{"type": "text", "text": "hello"}]),
        ]
    }


class _FakeAgent:
    async def aget_state(self, config: dict[str, object]) -> _FakeState:
        return _FakeState()


def test_get_thread_messages_serializes_checkpointer_state(
    monkeypatch: MonkeyPatch,
) -> None:
    """checkpointer 中的消息应被正确序列化为 ThreadMessage。"""
    monkeypatch.setattr(chat_service, "get_agent", lambda model_name: _FakeAgent())

    async def collect() -> list[ThreadMessage]:
        return await chat_service.get_thread_messages("test-model", "thread-1")

    messages = asyncio.run(collect())

    assert [(message.type, message.content) for message in messages] == [
        ("human", "hi"),
        ("ai", "hello"),
    ]


class _FakeSnapshot:
    """带 checkpoint_id 的状态快照，用于审计写入测试。"""

    config = {"configurable": {"thread_id": "thread-1", "checkpoint_id": "cp-1"}}
    values = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
        ]
    }


class _SnapshotAgent:
    async def aget_state(self, config: dict[str, object]) -> _FakeSnapshot:
        return _FakeSnapshot()


def test_record_run_checkpoint_persists_state(monkeypatch: MonkeyPatch) -> None:
    """record_run_checkpoint 应用线程 ID、checkpoint ID 和序列化后的消息调用存储层。"""
    recorded: dict[str, object] = {}

    # 拦截真正的数据库写入，仅记录调用参数
    async def fake_save_run_checkpoint(**kwargs: object) -> None:
        recorded.update(kwargs)

    monkeypatch.setattr(chat_service, "save_run_checkpoint", fake_save_run_checkpoint)

    asyncio.run(
        chat_service.record_run_checkpoint(
            _SnapshotAgent(),
            {"configurable": {"thread_id": "thread-1"}},
            "test-model",
        )
    )

    assert recorded["thread_id"] == "thread-1"
    assert recorded["checkpoint_id"] == "cp-1"
    assert recorded["model"] == "test-model"
    messages = recorded["messages"]
    assert isinstance(messages, list)
    assert [message["type"] for message in messages] == ["human", "ai"]
