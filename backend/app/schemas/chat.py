"""聊天相关的请求 / 响应模型（FastAPI 与 SSE 事件的类型定义）。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """POST /api/chat/stream 的请求体。"""

    message: str = Field(min_length=1)  # 用户输入，不允许空串
    model: str | None = None  # 缺省时使用模型列表中的第一个
    thread_id: str | None = None  # 会话 ID；相同 ID 复用历史，缺省则新建随机会话


class ModelListResponse(BaseModel):
    """GET /api/models 的响应体。"""

    models: list[str]


class ThreadMessage(BaseModel):
    """序列化后的单条消息（checkpointer / 审计 / 前端共用同一结构）。"""

    type: str  # human / ai / system / tool
    content: str
    id: str | None = None
    name: str | None = None  # tool 消息对应的工具名
    tool_call_id: str | None = None  # tool 消息对应的调用 ID
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)  # AI 发起的工具调用
    status: str | None = None  # tool 消息的执行状态：success / error
    hidden: bool = False  # 框架注入消息（如 skill 增删差分），对话视图不展示


class TokenUsage(BaseModel):
    """一次模型调用或一段时间内的 token 用量（对应 LangChain usage_metadata）。

    提取逻辑见 app/core/usage.py；子 agent 消耗经由 ToolMessage 并入。
    口径：input_tokens 不含缓存命中部分，cached_tokens 是独立的命中量，
    total_tokens 保持 provider 上报的总量（输入 + 缓存命中 + 输出）。
    """

    input_tokens: int = 0  # 输入（prompt）token 数，不含缓存命中部分
    output_tokens: int = 0  # 输出（completion）token 数
    total_tokens: int = 0  # provider 上报的总量：输入 + 缓存命中 + 输出
    cached_tokens: int = 0  # 命中 prompt 缓存的 token 数，provider 不上报时为 0


class ThreadSummary(BaseModel):
    """GET /api/chat/threads 的列表项：一个历史会话的摘要信息。

    数据来自 agent_run_checkpoints 审计表按 thread_id 聚合（取最新一条 run），
    因此 title / message_count 反映的是该会话最近一次运行结束时的状态。
    """

    thread_id: str  # 会话 ID（前端点击后用它拉取完整消息）
    title: str  # 展示标题：首条非隐藏用户消息的截断，无可用消息时的兜底文本
    message_count: int  # 最新 run 结束时的消息总数（不含隐藏消息的剔除逻辑，原样返回）
    model: str  # 最新 run 使用的模型名
    updated_at: datetime  # 最新 run 的落库时间（会话列表按此倒序）


class ThreadListResponse(BaseModel):
    """GET /api/chat/threads 的响应体。"""

    threads: list[ThreadSummary]


class ThreadMessagesResponse(BaseModel):
    """GET /api/chat/threads/{thread_id} 的响应体。"""

    thread_id: str
    system_prompt: str | None = None  # 不存 checkpointer，由配置单独带出，便于前端展示
    messages: list[ThreadMessage]
    # 整个会话的累计 token 用量：从 checkpointer 全部消息求和（与 done 事件口径一致），
    # 供前端切换历史会话时直接展示；内存模式或 provider 未上报时为 null
    total_usage: TokenUsage | None = None


class ChatStreamEvent(BaseModel):
    """SSE 事件。

    - token：增量文本；message_id 标识所属的 LLM 消息，前端据此归组到同一段文本；
    - reasoning：思维链增量（reasoning_content）；message_id 归组语义与 token 一致，
      仅思考型模型（GLM-4.5+ / DeepSeek-R1 等）会产生，其余模型不出现该事件；
    - tool_call：LLM 发起的工具调用（tool_call_id / name / args）；
    - tool_result：工具执行结果（tool_call_id 关联调用，status 为 success/error）；
    - error / done：错误信息与流结束。

    done 事件的用量统计见下方 turn_usage / total_usage 字段说明。
    """

    type: Literal[
        "token", "reasoning", "tool_call", "tool_result", "error", "done"
    ]
    content: str | None = None
    message_id: str | None = None
    tool_call_id: str | None = None
    name: str | None = None
    args: Any = None
    status: str | None = None
    message: str | None = None
    # 本轮合计：主 agent 各次模型调用之和 + 子 agent 用量（含工具循环的多次调用）
    turn_usage: TokenUsage | None = None
    # 整个会话累计：流结束后对 checkpointer 中全部消息求和（跨轮次）
    total_usage: TokenUsage | None = None
