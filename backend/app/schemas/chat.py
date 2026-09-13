"""聊天相关的请求 / 响应模型（FastAPI 与 SSE 事件的类型定义）。"""

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
    hidden: bool = False  # 框架注入消息（如 skill 增删差分），对话视图不展示


class ThreadMessagesResponse(BaseModel):
    """GET /api/chat/threads/{thread_id} 的响应体。"""

    thread_id: str
    system_prompt: str | None = None  # 不存 checkpointer，由配置单独带出，便于前端展示
    messages: list[ThreadMessage]


class ChatStreamEvent(BaseModel):
    """SSE 事件。

    - token：增量文本；message_id 标识所属的 LLM 消息，前端据此归组到同一段文本；
    - tool_call：LLM 发起的工具调用（tool_call_id / name / args）；
    - tool_result：工具执行结果（tool_call_id 关联调用，status 为 success/error）；
    - error / done：错误信息与流结束。
    """

    type: Literal["token", "tool_call", "tool_result", "error", "done"]
    content: str | None = None
    message_id: str | None = None
    tool_call_id: str | None = None
    name: str | None = None
    args: Any = None
    status: str | None = None
    message: str | None = None
