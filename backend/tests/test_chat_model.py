"""ReasoningChatOpenAI 单元测试：reasoning_content 增量的提取。

不访问网络：直接用 OpenAI 兼容接口的原始 chunk dict 调
_convert_chunk_to_generation_chunk（它正是线上报文到达该方法的形态，
中间只经过 SDK 解析与 model_dump，结构一致）。
"""

from langchain_core.messages import AIMessageChunk

from app.agents.chat_model import REASONING_DELTA_KEY, ReasoningChatOpenAI


def _model() -> ReasoningChatOpenAI:
    """构建不联网的模型实例（client 懒加载，api_key 任给即可）。"""
    return ReasoningChatOpenAI(model="glm-4.6", api_key="test-key")


def _chunk(delta: dict, **overrides: object) -> dict:
    """按 OpenAI 兼容接口的流式报文形状构造原始 chunk dict。"""
    choice: dict = {"index": 0, "delta": delta, "finish_reason": None}
    chunk: dict = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "model": "glm-4.6",
        "created": 1758000000,
        "choices": [choice],
    }
    chunk.update(overrides)
    return chunk


def test_reasoning_delta_extracted_into_additional_kwargs() -> None:
    """带 reasoning_content 的 delta：增量应出现在 additional_kwargs 上。"""
    generation = _model()._convert_chunk_to_generation_chunk(
        _chunk({"reasoning_content": "用户想要..."}), AIMessageChunk, None
    )
    assert generation is not None
    assert (
        generation.message.additional_kwargs[REASONING_DELTA_KEY] == "用户想要..."
    )
    # 父类的常规转换不受影响：正文仍为空（本帧只有思考增量）
    assert generation.message.content == ""


def test_plain_text_chunk_has_no_reasoning_key() -> None:
    """普通正文帧：不产生 reasoning 相关键，行为与父类一致。"""
    generation = _model()._convert_chunk_to_generation_chunk(
        _chunk({"content": "你好"}), AIMessageChunk, None
    )
    assert generation is not None
    assert generation.message.content == "你好"
    assert REASONING_DELTA_KEY not in generation.message.additional_kwargs


def test_role_only_first_chunk_is_ignored() -> None:
    """首帧只有 role（delta 无内容）：不报错、不产生 reasoning 键。"""
    generation = _model()._convert_chunk_to_generation_chunk(
        _chunk({"role": "assistant"}), AIMessageChunk, None
    )
    assert generation is not None
    assert REASONING_DELTA_KEY not in generation.message.additional_kwargs


def test_usage_only_frame_without_choices_is_passthrough() -> None:
    """纯 usage 帧（choices 为空）：父类返回空消息 chunk，覆写不引入异常。"""
    chunk = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "model": "glm-4.6",
        "created": 1758000000,
        "choices": [],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    generation = _model()._convert_chunk_to_generation_chunk(
        chunk, AIMessageChunk, None
    )
    assert generation is not None
    assert REASONING_DELTA_KEY not in generation.message.additional_kwargs


def test_empty_reasoning_string_is_not_stored() -> None:
    """reasoning_content 为空字符串：视为无增量，不写入空值。"""
    generation = _model()._convert_chunk_to_generation_chunk(
        _chunk({"reasoning_content": ""}), AIMessageChunk, None
    )
    assert generation is not None
    assert REASONING_DELTA_KEY not in generation.message.additional_kwargs
