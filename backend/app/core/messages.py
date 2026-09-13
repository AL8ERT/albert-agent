"""消息工具：从 LangChain 消息 content 中提取纯文本。

模型返回的 content 可能是：
- 字符串（普通文本）；
- 内容块列表（多模态 / 思考链场景），形如 [{"type": "text", "text": "..."}]。
这里只拼接文本块，忽略其他类型（如图片、工具调用）。
"""


def extract_text(content: object) -> str:
    """把消息 content 归一化为纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""
