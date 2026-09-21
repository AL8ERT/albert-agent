"""对话服务单元测试：SSE 错误处理、消息序列化、token 用量统计与 run 审计写入。

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

    def __init__(self, steps: list[tuple[str, Any]], state: Any = None) -> None:
        self.steps = steps
        self.state = state

    async def astream(self, *args: Any, **kwargs: Any):
        for step in self.steps:
            yield step

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return self.state


def test_stream_emits_intermediate_text_and_tool_events(
    monkeypatch: MonkeyPatch,
) -> None:
    """LLM 中间文本、思维链、工具调用与工具结果都应转成对应的 SSE 事件。

    - messages 模式的思维链增量（additional_kwargs.reasoning_content_delta）
      -> reasoning 事件（message_id 归组语义与 token 一致）；
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
            # 思考型模型：正文 token 之前先流出思维链增量
            (
                "messages",
                (
                    AIMessageChunk(
                        content="",
                        id="ai-1",
                        additional_kwargs={"reasoning_content_delta": "先想想 "},
                    ),
                    {},
                ),
            ),
            (
                "messages",
                (
                    AIMessageChunk(
                        content="",
                        id="ai-1",
                        additional_kwargs={"reasoning_content_delta": "再想想。"},
                    ),
                    {},
                ),
            ),
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
        {"type": "reasoning", "content": "先想想 ", "message_id": "ai-1"},
        {"type": "reasoning", "content": "再想想。", "message_id": "ai-1"},
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


def test_stream_reports_token_usage(monkeypatch: MonkeyPatch) -> None:
    """done 事件应携带本轮与整个会话的 token 用量统计。

    - turn_usage：本轮全部模型调用（工具循环产生多条 AIMessage）用量之和；
    - total_usage：checkpointer state 中全部消息之和（含历史轮次）；
    - 子 agent 用量（use_subagent 写入 ToolMessage 的 subagent_usage）并入两者；
    - cached_tokens 取自 input_token_details，未上报时为 0；
    - input_tokens 为 provider 原始输入扣除缓存命中后的口径。
    """
    first_ai = AIMessage(
        content="Let me search.",
        id="ai-1",
        tool_calls=[
            {"name": "use_subagent", "args": {"agent_name": "general"}, "id": "call-1"}
        ],
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            # langchain-openai 1.x 用 cache_read 作为缓存命中键名
            "input_token_details": {"cache_read": 40},
        },
    )
    # use_subagent 的返回：additional_kwargs 带子 agent 用量合计
    subagent_result = ToolMessage(
        content="subagent answer",
        tool_call_id="call-1",
        name="use_subagent",
        additional_kwargs={
            "subagent_usage": {
                "input_tokens": 50,
                "output_tokens": 5,
                "total_tokens": 55,
                "cached_tokens": 0,
            }
        },
    )
    final_ai = AIMessage(
        content="Done",
        id="ai-2",
        usage_metadata={
            "input_tokens": 200,
            "output_tokens": 20,
            "total_tokens": 220,
            "input_token_details": {},  # 无缓存命中的调用
        },
    )
    # 上一轮的历史消息：应计入 total_usage，不计入 turn_usage
    history_ai = AIMessage(
        content="old turn",
        usage_metadata={
            "input_tokens": 1000,
            "output_tokens": 100,
            "total_tokens": 1100,
        },
    )
    # 无 usage_metadata 的消息不应参与统计
    history_without_usage = AIMessage(content="legacy turn")

    class _UsageState:
        config = {"configurable": {"checkpoint_id": "cp-usage"}}
        values = {
            "messages": [
                history_ai,
                history_without_usage,
                first_ai,
                subagent_result,
                final_ai,
            ]
        }

    agent = _StreamAgent(
        [
            ("updates", {"model": {"messages": [first_ai]}}),
            ("updates", {"tools": {"messages": [subagent_result]}}),
            ("updates", {"model": {"messages": [final_ai]}}),
        ],
        state=_UsageState(),
    )
    monkeypatch.setattr(chat_service, "get_agent", lambda model_name: agent)

    async def noop_save(**kwargs: object) -> None:
        pass

    monkeypatch.setattr(chat_service, "save_run_checkpoint", noop_save)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in chat_service.stream_chat_reply("hi", "test-model")
        ]

    raw_chunks = asyncio.run(collect())
    done = json.loads(raw_chunks[-1].removeprefix("data: ").strip())

    assert done["type"] == "done"
    # 主 agent 两次调用 + 子 agent 一次合计（首次 100 扣除缓存 40 后为 60）
    assert done["turn_usage"] == {
        "input_tokens": 310,
        "output_tokens": 35,
        "total_tokens": 385,
        "cached_tokens": 40,
    }
    # 历史轮次 + 本轮全部
    assert done["total_usage"] == {
        "input_tokens": 1310,
        "output_tokens": 135,
        "total_tokens": 1485,
        "cached_tokens": 40,
    }


def test_stream_done_without_usage_stays_minimal(
    monkeypatch: MonkeyPatch,
) -> None:
    """provider 未上报 usage_metadata 时，done 事件不携带用量字段（向后兼容）。"""
    agent = _StreamAgent(
        [("updates", {"model": {"messages": [AIMessage(content="hi", id="ai-1")]}})],
    )
    monkeypatch.setattr(chat_service, "get_agent", lambda model_name: agent)

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in chat_service.stream_chat_reply("hi", "test-model")
        ]

    raw_chunks = asyncio.run(collect())
    done = json.loads(raw_chunks[-1].removeprefix("data: ").strip())

    assert done == {"type": "done"}


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
    """checkpointer 中的消息应被正确序列化为 ThreadMessage，并附带会话累计用量。"""
    monkeypatch.setattr(chat_service, "get_agent", lambda model_name: _FakeAgent())

    async def collect() -> tuple[list[ThreadMessage], object]:
        return await chat_service.get_thread_messages("test-model", "thread-1")

    messages, _usage = asyncio.run(collect())

    assert [(message.type, message.content) for message in messages] == [
        ("human", "hi"),
        ("ai", "hello"),
    ]


class _UsageState:
    """带用量消息的状态快照：get_thread_messages 应求和返回 total_usage。"""

    values = {
        "messages": [
            HumanMessage(content="hi"),
            AIMessage(
                content="hello",
                usage_metadata={
                    "input_tokens": 100,
                    "output_tokens": 10,
                    "total_tokens": 110,
                    "input_token_details": {"cache_read": 40},
                },
            ),
        ]
    }


class _UsageAgent:
    async def aget_state(self, config: dict[str, object]) -> _UsageState:
        return _UsageState()


def test_get_thread_messages_returns_total_usage(
    monkeypatch: MonkeyPatch,
) -> None:
    """会话累计用量应与 SSE done 事件同口径（AI 消息 usage_metadata 求和）。"""
    monkeypatch.setattr(chat_service, "get_agent", lambda model_name: _UsageAgent())

    async def collect() -> object:
        return await chat_service.get_thread_messages("test-model", "thread-1")

    _messages, usage = asyncio.run(collect())

    assert usage is not None
    # provider 原始输入 100 扣除缓存命中 40 后为 60
    assert usage.input_tokens == 60
    assert usage.cached_tokens == 40


def test_list_threads_builds_summaries_from_audit_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    """list_threads 应把审计表原始行组装成摘要：标题取首条非隐藏用户消息。"""
    from datetime import datetime

    rows = [
        # (thread_id, model, message_count, messages, created_at)
        (
            "thread-2",
            "deepseek-flash",
            4,
            [
                {"type": "human", "content": "", "hidden": False},
                {"type": "human", "content": "第二条会话的问题", "hidden": False},
                {"type": "ai", "content": "回答", "hidden": False},
            ],
            datetime(2026, 9, 20, 12, 0, 0),
        ),
        (
            "thread-1",
            "deepseek-flash",
            2,
            [
                # 首条 human 是框架注入的隐藏消息，应被跳过
                {"type": "human", "content": "<available_skills>", "hidden": True},
                {"type": "human", "content": "你好" * 30, "hidden": False},
                {"type": "ai", "content": "你好！", "hidden": False},
            ],
            datetime(2026, 9, 19, 9, 0, 0),
        ),
    ]

    async def fake_list_thread_runs(limit: int = 50) -> list[tuple]:
        return rows  # type: ignore[return-value]

    monkeypatch.setattr(chat_service, "list_thread_runs", fake_list_thread_runs)

    async def collect() -> list[object]:
        return await chat_service.list_threads()

    threads = asyncio.run(collect())

    # 数据库层已按时间倒序，服务层保持顺序原样透传
    assert [summary.thread_id for summary in threads] == ["thread-2", "thread-1"]
    first, second = threads
    # 空内容的 human 消息不能当标题，取下一条有效用户消息
    assert first.title == "第二条会话的问题"
    assert first.message_count == 4
    # 隐藏消息跳过 + 超长标题截断到 40 字符
    assert second.title == "你好" * 20
    assert second.updated_at.year == 2026


def test_list_threads_without_database_returns_empty(
    monkeypatch: MonkeyPatch,
) -> None:
    """未配置 PostgreSQL 时数据层返回空列表，服务层原样给出空历史。"""

    async def fake_list_thread_runs(limit: int = 50) -> list[tuple]:
        return []

    monkeypatch.setattr(chat_service, "list_thread_runs", fake_list_thread_runs)

    async def collect() -> list[object]:
        return await chat_service.list_threads()

    assert asyncio.run(collect()) == []


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
