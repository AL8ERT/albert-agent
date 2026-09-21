"""兼容 OpenAI 协议且保留思维链（reasoning_content）的 ChatOpenAI 子类。

langchain-openai 只提取 OpenAI API 规范字段，第三方 provider（GLM / DeepSeek /
Qwen 等）在流式 delta 里返回的 reasoning_content 字段会在内部转换时被静默丢弃，
官方 docstring 建议此类场景使用 provider 专属子类。本模块即为该子类：
继承 ChatOpenAI，在原始 chunk 的唯一转换入口补提取 reasoning_content 增量，
写入消息的 additional_kwargs，供 SSE 层逐段转发给前端。

数据路径（streaming=True 时 invoke / astream 都走这条路）：

    provider SSE 报文（原始 JSON）
      -> openai SDK 解析成 ChatCompletionChunk（extra="allow"，非标字段保留）
      -> langchain-openai 的 _astream 里 model_dump() 回 dict
      -> _convert_chunk_to_generation_chunk(chunk, ...)   <- 本模块唯一覆写点
      -> run_manager.on_llm_new_token(text, chunk=generation)
      -> langgraph messages 流模式 / LangChain 各级消费者（chat_service 在此读取）
"""

from typing import Any

from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

# 增量思维链文本在 additional_kwargs 里的键名。
# 定义成模块级常量供 chat_service 同名 import，避免魔法字符串散落两处。
# 刻意命名为 ..._delta：每帧只携带一小段增量，与「全量」（聚合后消息上的
# 完整思考文本，历史回放场景预留）语义区分开。
REASONING_DELTA_KEY = "reasoning_content_delta"

__all__ = ["REASONING_DELTA_KEY", "ReasoningChatOpenAI"]


class ReasoningChatOpenAI(ChatOpenAI):
    """ChatOpenAI 子类：保留 OpenAI 兼容 provider 返回的 reasoning_content。

    只覆写一个转换方法，其余行为（streaming / stream_usage / 请求构造 /
    工具调用）与 ChatOpenAI 完全一致。
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,  # provider 返回的原始 chunk（SDK 解析后 dump 的 dict），
        #   形如 {"choices": [{"delta": {"reasoning_content": "...", ...}}], ...}
        default_chunk_class: type,  # 父类内部维护的下一 chunk 消息类型，原样透传
        base_generation_info: dict | None,  # 父类内部维护的首个 chunk 附加信息，原样透传
    ) -> ChatGenerationChunk | None:
        """把原始 chunk dict 转成 LangChain 消息增量，并补提取思维链字段。

        父类实现只提取 content / tool_calls / id / role 等 OpenAI 规范字段，
        delta 里的 reasoning_content 在父类中被丢弃 —— 因此在 super() 转换完
        之后在其结果上补取，不重复实现任何父类逻辑。
        """
        # 先调父类完成常规转换（正文 / 工具调用 / usage 等）
        generation = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        # 父类对无有效内容的帧（如纯 usage 帧）返回 None，
        # 此时没有消息对象可挂 additional_kwargs，直接跳过
        if generation is not None:
            # 父类取 choices 时优先 "choices" 键，兜底 "chunk".choices
            # （beta.chat.completions.stream 接口的包裹格式），这里保持同样取法
            choices = chunk.get("choices") or chunk.get("chunk", {}).get(
                "choices", []
            )
            # chat completions 的流式增量在 delta 键里；
            # 首 chunk 只带 role（delta 为 None），判空避免 KeyError
            if choices and choices[0].get("delta"):
                # 取出这一帧的思考增量文本（GLM / DeepSeek / Qwen 的通用字段名）
                reasoning = choices[0]["delta"].get("reasoning_content")
                # 空字符串 / 字段缺失时不写键，避免产生无意义的 kwargs 条目
                if reasoning:
                    # 挂到消息的 additional_kwargs：LangChain 官方的自定义元数据
                    # 扩展位，会随 chunk 穿透回调管道直达 chat_service；
                    # 不放进 content 是为了避免混进正文被当成 token 事件发出
                    generation.message.additional_kwargs[REASONING_DELTA_KEY] = (
                        reasoning
                    )
        # 把（可能加料过的）转换结果交还框架，后续行为与父类完全一致
        return generation
