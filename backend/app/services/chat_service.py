"""对话服务：把 agent 的执行过程转成 SSE 事件，并提供线程消息读取/审计写入。

数据流：
  前端 POST /api/chat/stream
    -> stream_chat_reply() 调用 agent.astream(stream_mode=["messages", "updates"])
    -> messages：增量 AIMessageChunk 转成 {"type":"token"}（LLM 文本，含中间文本）；
       思考型模型的思维链增量（additional_kwargs 的 reasoning_content_delta）
       转成 {"type":"reasoning"}，与 token 同构但独立归组
    -> updates：节点产出的完整消息转成工具事件
       AI 消息的 tool_calls -> {"type":"tool_call"}，ToolMessage -> {"type":"tool_result"}
       用量在此时累计（app.core.usage）：AI 消息的 usage_metadata 是主 agent 各次
       模型调用，use_subagent 的 ToolMessage 带子 agent 用量合计
    -> 流结束后读取 checkpointer 最新 state：写入 agent_run_checkpoints 审计表，
       并对全部消息的用量求和得到整个会话的累计用量
    -> 最后发送 {"type":"done"} 结束事件，携带 turn_usage / total_usage
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
from app.agents.chat_model import REASONING_DELTA_KEY
from app.core.database import list_thread_runs
from app.core.database import save_run_checkpoint
from app.core.messages import extract_text
from app.core.usage import messages_usage, sum_usages, usage_from_message
from app.schemas.chat import (
    ChatStreamEvent,
    ThreadMessage,
    ThreadSummary,
    TokenUsage,
)

logger = logging.getLogger(__name__)

# 历史会话标题的最大长度（首条用户消息超长时截断）
THREAD_TITLE_MAX_LEN = 40


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
        status=getattr(message, "status", None),
        hidden=bool(additional.get("hide_from_chat")),
    )


def _thread_title(messages: list[dict[str, Any]]) -> str:
    """从审计表消息列表提取会话标题：首条非隐藏用户消息的截断。

    - 跳过 hidden 消息（技能 / 子 agent 名单等框架注入内容不适合做标题）；
    - 找不到可用消息（理论上不该发生）时返回兜底文本，避免空标题。
    """
    for message in messages:
        if message.get("type") == "human" and not message.get("hidden"):
            content = str(message.get("content") or "").strip()
            if content:
                # 单字符级截断：中文标题不会被从中间截断产生乱码（Python 按字符切片）
                return content[:THREAD_TITLE_MAX_LEN]
    return "（无标题会话）"


async def list_threads(limit: int = 50) -> list[ThreadSummary]:
    """历史会话列表：每个 thread 取最新一条 run 聚合成摘要，按时间倒序。

    数据源是 agent_run_checkpoints 审计表（每轮对话成功结束都会落一条），
    未配置 PostgreSQL 时自然为空。读取异常在 database 层已被兜底成空列表。
    """
    rows = await list_thread_runs(limit)
    return [
        ThreadSummary(
            thread_id=thread_id,
            title=_thread_title(messages),
            message_count=message_count,
            model=model,
            updated_at=created_at,
        )
        for thread_id, model, message_count, messages, created_at in rows
    ]


async def get_thread_messages(
    model_name: str, thread_id: str
) -> tuple[list[ThreadMessage], TokenUsage | None]:
    """读取某个线程在 checkpointer 中的全部消息，并附带会话累计用量。

    注意：create_agent 的 system prompt 不写入 state，因此这里天然不包含它；
    系统提示词由 API 层从配置中单独返回给前端。
    返回 (messages, total_usage)：用量对全部消息求和，与 SSE done 事件同口径，
    供前端切换历史会话时直接展示。
    """
    agent = get_agent(model_name)
    state = await agent.aget_state({"configurable": {"thread_id": thread_id}})
    raw: list[Any] = state.values.get("messages", []) if state is not None else []
    messages = [serialize_message(message) for message in raw]
    return messages, messages_usage(raw)


async def record_run_checkpoint(
    agent: Any,
    config: dict[str, Any],
    model_name: str,
    *,
    state: Any | None = None,
) -> None:
    """把本次 run 结束后的完整 state 快照写入 PostgreSQL 审计表。

    调用方可传入已读取的 state 避免重复 aget_state（流结束时服务层会先读一次
    用于统计会话累计用量）；未传时自行读取。任何异常都被吞掉（记录日志），
    避免审计失败影响已经完成的对话。
    """
    try:
        if state is None:
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
    - done 事件携带用量统计：turn_usage 为本轮各次模型调用之和（含子 agent
      用量），total_usage 为 checkpointer 中整个会话的消息用量求和（provider 未上报时为 null）。
    - 无论成功失败，最后都会发送 done 事件，前端据此结束加载状态。
    """
    turn_usages: list[TokenUsage] = []  # 本轮逐次模型调用 / 子 agent 的用量累计
    total_usage: TokenUsage | None = None  # 会话累计，流结束后从最终 state 求得
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
                    # 思维链增量：ReasoningChatOpenAI 在流式 chunk 的
                    # additional_kwargs 里携带（第三方 provider 的
                    # reasoning_content 字段，非思考模型 / 普通文本帧不会有）
                    reasoning = chunk.additional_kwargs.get(REASONING_DELTA_KEY)
                    if reasoning:
                        # 与 token 事件同构（content 为增量、message_id 归组），
                        # 前端按类型分别归组到思考块与文本块
                        yield format_sse(
                            ChatStreamEvent(
                                type="reasoning",
                                content=reasoning,
                                message_id=chunk.id,
                            )
                        )
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
                    node_messages = update.get("messages") or []
                    # 模型节点的聚合 AIMessage 携带本次调用的 usage_metadata，
                    # use_subagent 的 ToolMessage 携带子 agent 用量合计，
                    # 全部累计即为本轮用量（工具循环会产生多条）
                    for node_message in node_messages:
                        usage = usage_from_message(node_message)
                        if usage is not None:
                            turn_usages.append(usage)
                    for event in _node_events(node_messages):
                        yield format_sse(event)
        # 流结束后读一次最终 state：会话累计用量与审计快照共用这次读取
        try:
            state = await agent.aget_state(config)
        except Exception:
            # 读取失败只影响统计与审计，不影响已完成的对话本身
            logger.exception("Failed to read final thread state")
            state = None
        if state is not None:
            total_usage = messages_usage(state.values.get("messages") or [])
        # 落审计快照；record_run_checkpoint 内部已做异常兜底（state 为 None 时会自行重读）
        await record_run_checkpoint(agent, config, model_name, state=state)
    except Exception as exc:
        # 把异常转成 error 事件，前端会展示错误信息
        yield format_sse(ChatStreamEvent(type="error", message=str(exc)))
    finally:
        # 出错时 turn_usage 可能是部分累计，仍然带出（真实消耗了就应可见）
        yield format_sse(
            ChatStreamEvent(
                type="done",
                turn_usage=sum_usages(turn_usages),
                total_usage=total_usage,
            )
        )
