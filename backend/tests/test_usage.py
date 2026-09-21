"""token 用量提取测试：缓存命中字段的键名兼容与 input 口径换算。

langchain-openai >= 1.x 把缓存命中映射为 input_token_details["cache_read"]，
旧版与部分 provider 使用 "cached_tokens"，两种键都要能读到。
provider 的 input_tokens 含缓存命中，提取时扣除得到不含缓存的输入量；
已存储的 TokenUsage（子 agent 用量）写入时已是该口径，读取时不再二次扣除。
"""

from langchain.messages import AIMessage, HumanMessage, ToolMessage

from app.core.usage import (
    SUBAGENT_USAGE_KEY,
    messages_usage,
    sum_usages,
    usage_from_message,
)
from app.schemas.chat import TokenUsage


def _ai(usage: dict) -> AIMessage:
    return AIMessage(content="hi", usage_metadata=usage)


def test_reads_cache_read_key() -> None:
    """langchain-openai 1.x 的标准键：cache_read；input 扣除命中部分。"""
    message = _ai(
        {
            "input_tokens": 1258,
            "output_tokens": 100,
            "total_tokens": 1358,
            "input_token_details": {"cache_read": 1024},
        }
    )

    usage = usage_from_message(message)

    assert usage == TokenUsage(
        input_tokens=234,
        output_tokens=100,
        total_tokens=1358,
        cached_tokens=1024,
    )


def test_reads_legacy_cached_tokens_key() -> None:
    """旧版键名 cached_tokens 仍然生效。"""
    message = _ai(
        {
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            "input_token_details": {"cached_tokens": 60},
        }
    )

    assert usage_from_message(message) == TokenUsage(
        input_tokens=40, output_tokens=10, total_tokens=110, cached_tokens=60
    )


def test_prefers_cache_read_over_cached_tokens() -> None:
    """两个键同时存在时以 cache_read 为准（新版本行为）。"""
    message = _ai(
        {
            "input_tokens": 100,
            "output_tokens": 10,
            "total_tokens": 110,
            "input_token_details": {"cache_read": 70, "cached_tokens": 999},
        }
    )

    usage = usage_from_message(message)

    assert usage.cached_tokens == 70
    assert usage.input_tokens == 30


def test_input_tokens_never_negative() -> None:
    """provider 上报异常（命中量大于输入总量）时，input_tokens 截断为 0。"""
    message = _ai(
        {
            "input_tokens": 10,
            "output_tokens": 1,
            "total_tokens": 11,
            "input_token_details": {"cache_read": 20},
        }
    )

    usage = usage_from_message(message)

    assert usage is not None
    assert usage.input_tokens == 0
    assert usage.cached_tokens == 20


def test_missing_details_default_to_zero() -> None:
    message = _ai({"input_tokens": 5, "output_tokens": 1, "total_tokens": 6})

    usage = usage_from_message(message)

    assert usage == TokenUsage(
        input_tokens=5, output_tokens=1, total_tokens=6, cached_tokens=0
    )


def test_usage_from_subagent_tool_message() -> None:
    """ToolMessage 的子 agent 用量合计：存储格式已是新口径，读取时不再二次扣除。"""
    message = ToolMessage(
        content="answer",
        tool_call_id="call-1",
        additional_kwargs={
            SUBAGENT_USAGE_KEY: {
                "input_tokens": 50,
                "output_tokens": 5,
                "total_tokens": 55,
                "cached_tokens": 20,
            }
        },
    )

    assert usage_from_message(message) == TokenUsage(
        input_tokens=50, output_tokens=5, total_tokens=55, cached_tokens=20
    )


def test_messages_usage_and_sum_cover_mixed_messages() -> None:
    """混排消息求和：AI 消息（新键）+ 子 agent ToolMessage，无关消息跳过。"""
    messages = [
        HumanMessage(content="hi"),
        _ai(
            {
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "input_token_details": {"cache_read": 40},
            }
        ),
        ToolMessage(content="r", tool_call_id="c"),
        ToolMessage(
            content="answer",
            tool_call_id="c2",
            additional_kwargs={
                SUBAGENT_USAGE_KEY: {
                    "input_tokens": 50,
                    "output_tokens": 5,
                    "total_tokens": 55,
                    "cached_tokens": 20,
                }
            },
        ),
    ]

    assert messages_usage(messages) == sum_usages(
        [
            # AI 消息：provider 原始 input 100 含缓存 40，换算后为 60
            TokenUsage(
                input_tokens=60, output_tokens=10, total_tokens=110, cached_tokens=40
            ),
            TokenUsage(
                input_tokens=50, output_tokens=5, total_tokens=55, cached_tokens=20
            ),
        ]
    )
