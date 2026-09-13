"""聊天路由：SSE 流式对话 + 读取线程消息。"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agents.assistant import build_system_prompt
from app.core.config import get_models
from app.schemas.chat import ChatRequest, ThreadMessagesResponse
from app.services.chat_service import get_thread_messages, stream_chat_reply

router = APIRouter(prefix="/chat", tags=["chat"])

# SSE 响应头：禁用各级缓存与代理缓冲，保证 token 实时到达前端
STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # Nginx 等反向代理下不缓冲
}


def _resolve_model(model: str | None) -> str:
    """校验并解析模型名；缺省时取列表第一个。

    - 没有任何模型配置 -> 503
    - 指定了未知模型 -> 400
    """
    available = get_models()
    if not available:
        raise HTTPException(
            status_code=503,
            detail="No model is configured. Create .albert-agent/albert-agent-config.json in your home directory.",
        )

    model_name = model or available[0].name
    if all(entry.name != model_name for entry in available):
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_name}")
    return model_name


@router.post("/stream")
async def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """发送消息并返回 SSE 流（token / error / done 事件）。"""
    model_name = _resolve_model(payload.model)

    return StreamingResponse(
        stream_chat_reply(payload.message, model_name, payload.thread_id),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    model: str | None = None,
) -> ThreadMessagesResponse:
    """读取指定线程在 checkpointer 中的消息，并附带当前系统提示词。

    system_prompt 来自配置而非 checkpointer：create_agent 只在调用模型时注入它，
    因此 state 里没有；这里单独返回，让前端可以完整查看"实际使用的提示词"。
    """
    model_name = _resolve_model(model)
    messages = await get_thread_messages(model_name, thread_id)
    return ThreadMessagesResponse(
        thread_id=thread_id,
        system_prompt=build_system_prompt(),
        messages=messages,
    )
