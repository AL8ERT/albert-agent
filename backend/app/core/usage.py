"""token 用量提取与汇总（主流向 turn_usage 与会话向 total_usage 共用）。

两个来源，都随 checkpointer 持久化，重启 / PostgreSQL 下统计仍准确：

- 主 agent：每次模型调用的聚合 AIMessage.usage_metadata（模型以
  ``stream_usage=True`` 创建时由流式响应的最终 chunk 携带）；
- 子 agent：``use_subagent`` 把子 agent 全部用量合计写入 ToolMessage 的
  ``additional_kwargs["subagent_usage"]``（ToolMessage 原样进入主线程 state）。

口径：provider 的 ``input_tokens`` 是含缓存命中的输入总量，提取时扣除
``cached_tokens`` 得到本项目的 ``input_tokens``（不含缓存命中）；子 agent
用量以 TokenUsage 形式存储，读取时不再二次扣除。
"""

from typing import Any

from langchain.messages import AIMessage, ToolMessage

from app.schemas.chat import TokenUsage

# ToolMessage.additional_kwargs 里存放子 agent 用量合计的键名
SUBAGENT_USAGE_KEY = "subagent_usage"


def _from_raw_usage_metadata(usage: Any) -> TokenUsage | None:
    """把 provider 上报的 usage_metadata 转成 TokenUsage；空值返回 None。

    provider 的 input_tokens 是含缓存命中的输入总量，这里扣除命中部分，
    换算成本项目的 input_tokens 口径（不含缓存命中）。
    缓存命中按键名优先级依次回退：新版键 cache_read -> 旧版嵌套键
    cached_tokens -> 顶层 cached_tokens（部分 provider 的扁平结构）。
    """
    if not isinstance(usage, dict) or not usage:
        return None
    details = usage.get("input_token_details") or {}
    cached = details.get("cache_read")
    if cached is None:
        cached = details.get("cached_tokens")
    if cached is None:
        cached = usage.get("cached_tokens")
    cached_tokens = int(cached or 0)
    # 各字段缺失时按 0 处理（部分 provider 只返回部分字段）；扣除后不出现负数
    input_tokens = int(usage.get("input_tokens") or 0)
    return TokenUsage(
        input_tokens=max(input_tokens - cached_tokens, 0),
        output_tokens=int(usage.get("output_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        cached_tokens=cached_tokens,
    )


def _from_stored_usage(usage: Any) -> TokenUsage | None:
    """读取 ToolMessage 中持久化的 TokenUsage（subagent_usage）；空值返回 None。

    存储格式是 ``TokenUsage.model_dump()``，写入时已是新口径，
    直接校验还原即可，避免对 input_tokens 二次扣除缓存命中。
    """
    if not isinstance(usage, dict) or not usage:
        return None
    return TokenUsage.model_validate(usage)


def usage_from_message(message: Any) -> TokenUsage | None:
    """按消息类型提取用量，未上报时返回 None。

    - AIMessage：本次模型调用的 usage_metadata（provider 原始结构）；
    - ToolMessage：additional_kwargs 里已换算好的子 agent 用量合计。
    """
    if isinstance(message, AIMessage):
        return _from_raw_usage_metadata(getattr(message, "usage_metadata", None))
    if isinstance(message, ToolMessage):
        additional = getattr(message, "additional_kwargs", None) or {}
        return _from_stored_usage(additional.get(SUBAGENT_USAGE_KEY))
    return None


def sum_usages(usages: list[TokenUsage]) -> TokenUsage | None:
    """把多份用量累加成一份；列表为空（provider 未上报）时返回 None。"""
    if not usages:
        return None
    # 逐字段求和；input_tokens（不含缓存）与 cached_tokens（命中量）相互独立
    return TokenUsage(
        input_tokens=sum(item.input_tokens for item in usages),
        output_tokens=sum(item.output_tokens for item in usages),
        total_tokens=sum(item.total_tokens for item in usages),
        cached_tokens=sum(item.cached_tokens for item in usages),
    )


def messages_usage(messages: list[Any]) -> TokenUsage | None:
    """对一组消息求和：AI 消息用量 + ToolMessage 携带的子 agent 用量。"""
    # 海象表达式逐条提取，跳过未上报用量的消息（usage 为 None）
    return sum_usages(
        [
            usage
            for message in messages
            if (usage := usage_from_message(message)) is not None
        ]
    )
