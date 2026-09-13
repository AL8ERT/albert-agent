"""对话服务：把 agent 的执行过程转成 SSE 事件，并提供线程消息读取/审计写入。

数据流：
  前端 POST /api/chat/stream
    -> stream_chat_reply() 调用 agent.astream(stream_mode=["messages", "updates"])
    -> messages：增量 AIMessageChunk 转成 {"type":"token"}（LLM 文本，含中间文本）
    -> updates：节点产出的完整消息转成工具事件
       AI 消息的 tool_calls -> {"type":"tool_call"}，ToolMessage -> {"type":"tool_result"}
    -> 流结束后读取 checkpointer 最新 state，写入 agent_run_checkpoints 审计表
    -> 最后发送 {"type":"done"} 结束事件
"""

import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

from langchain.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    HumanMessage,
    ToolMessage,
)

from app.agents.assistant import build_system_prompt, get_agent
from app.core.database import save_run_checkpoint
from app.core.messages import extract_text
from app.schemas.chat import ChatStreamEvent, ThreadMessage

logger = logging.getLogger(__name__)


def format_sse(event: ChatStreamEvent) -> str:
    """把事件对象格式化为 SSE 数据帧（data: {...} + 空行）。"""
    return f"data: {event.model_dump_json(exclude_none=True)}\n\n"


def serialize_message(message: AnyMessage) -> ThreadMessage:
    """把 LangChain 消息对象转成 API / 审计表使用的扁平结构。"""
    additional = getattr(message, "additional_kwargs", None) or {}
    return ThreadMessage(
        type=message.type,  # human / ai / system / tool
        content=extract_text(message.content),
        id=getattr(message, "id", None),
        name=getattr(message, "name", None),
        tool_call_id=getattr(message, "tool_call_id", None),
        tool_calls=[dict(call) for call in getattr(message, "tool_calls", [])],
        hidden=bool(additional.get("hide_from_chat")),
    )


async def get_thread_messages(model_name: str, thread_id: str) -> list[ThreadMessage]:
    """读取某个线程在 checkpointer 中的全部消息。

    注意：create_agent 的 system prompt 不写入 state，因此这里天然不包含它；
    系统提示词由 API 层从配置中单独返回给前端。
    """
    agent = get_agent(model_name)
    state = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    raw: list[Any] = state.values.get("messages", []) if state is not None else []
    return [serialize_message(message) for message in raw]


async def record_run_checkpoint(
    agent: Any,
    config: dict[str, Any],
    model_name: str,
) -> None:
    """把本次 run 结束后的完整 state 快照写入 PostgreSQL 审计表。

    仅在流成功结束后调用；任何异常都被吞掉（记录日志），
    避免审计失败影响已经完成的对话。
    """
    try:
        state = await agent.aget_state(config)
        checkpoint_id = None
        if state is not None:
            # checkpoint_id 标识这次 run 产生的 checkpoint，用于审计表去重
            checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")
        if not checkpoint_id:
            return

        raw: list[Any] = state.values.get("messages", [])
        await save_run_checkpoint(
            thread_id=config["configurable"]["thread_id"],
            checkpoint_id=checkpoint_id,
            model=model_name,
            system_prompt=build_system_prompt(),
            messages=[
                serialize_message(message).model_dump() for message in raw
            ],
        )
    except Exception:
        logger.exception("Failed to record run checkpoint")


def _node_events(messages: list[Any]) -> Iterator[ChatStreamEvent]:
    """把一次节点更新里的完整消息转成工具调用 / 工具结果事件。

    updates 模式在节点完成后产出完整消息：AI 消息的 tool_calls 是工具调用
    请求，ToolMessage 是执行结果；文本内容不在这里重复发送（messages 模式
    已经把增量文本作为 token 事件发出）。
    """
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                yield ChatStreamEvent(
                    type="tool_call",
                    tool_call_id=str(call.get("id") or ""),
                    name=str(call.get("name") or ""),
                    args=call.get("args"),
                    message_id=message.id,
                )
        elif isinstance(message, ToolMessage):
            yield ChatStreamEvent(
                type="tool_result",
                tool_call_id=message.tool_call_id,
                name=message.name,
                content=extract_text(message.content),
                status=message.status,
            )


async def stream_chat_reply(
    message: str,
    model_name: str,
    thread_id: str | None = None,
) -> AsyncIterator[str]:
    """执行一轮对话并以 SSE 字符串流的形式产出结果。

    - thread_id 相同 => 复用 checkpointer 中的历史，实现多轮对话；
      未传时生成随机 ID（相当于开启一个全新会话，避免所有匿名请求共享上下文）。
    - 中间过程可见：LLM 的中间文本逐 token 推送，工具调用与结果在节点完成时推送。
    - 无论成功失败，最后都会发送 done 事件，前端据此结束加载状态。
    """
    try:
        agent = get_agent(model_name)
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id or uuid4().hex}}
        # 同时订阅两种流：messages 逐 token（含中间文本），updates 节点完整消息
        async for mode, payload in agent.astream(
            {"messages": [HumanMessage(content=message)]},
            stream_mode=["messages", "updates"],
            config=config,
        ):
            if mode == "messages":
                chunk, _metadata = payload
                # 原生流式模型产出 AIMessageChunk；不支持流式时回退为完整 AIMessage
                if isinstance(chunk, (AIMessage, AIMessageChunk)):
                    text = extract_text(chunk.content)
                    if text:
                        yield format_sse(
                            ChatStreamEvent(
                                type="token",
                                content=text,
                                message_id=chunk.id,
                            )
                        )
            elif mode == "updates":
                for update in payload.values():
                    if not isinstance(update, dict):
                        continue
                    for event in _node_events(update.get("messages") or []):
                        yield format_sse(event)
        # 流结束后落审计快照；record_run_checkpoint 内部已做异常兜底
        await record_run_checkpoint(agent, config, model_name)
    except Exception as exc:
        # 把异常转成 error 事件，前端会展示错误信息
        yield format_sse(ChatStreamEvent(type="error", message=str(exc)))
    finally:
        yield format_sse(ChatStreamEvent(type="done"))
