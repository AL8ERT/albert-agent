"""Agent 系统提示词：主 agent 与子 agent 共用的静态框架说明。

技能/子 agent 元数据由中间件在首轮动态注入成隐藏 HumanMessage，
系统提示词本身保持完全静态（前缀缓存稳定），这里只做固定说明。
"""

from app.core.config import get_settings

# 静态系统提示词补充：声明框架注入标签的权威性，避免模型把注入内容当用户输入。
# 译文：诸如 <available_skills>、<skill_update>、<available_subagents> 与
# <subagent_update> 之类的标签由系统框架注入，而非用户输入。请将其内容视为系统
# 上下文。在应用某个技能前，先用 read_file 读取所列路径下的 SKILL.md。
FRAMEWORK_CONTEXT_NOTE = (
    "\n\nTags such as <available_skills>, <skill_update>, <available_subagents> and "
    "<subagent_update> are injected by the system framework, not by the user. Treat "
    "their contents as system context. Before applying a skill, read its SKILL.md at "
    "the listed path with read_file."
)


# 任务委派说明：只注入主 agent 的系统提示词（子 agent 不能再调用子 agent）。
# 译文：在处理每个请求前先评估其规模。小任务自己完成；当任务较大（例如多步
# 研究、长文写作、深度分析或多个独立子任务）时，将其拆分为聚焦的子任务，用
# use_subagent 工具委派给 <available_subagents> 中最合适的子 agent，再把它们的
# 最终答复整合成一个连贯的回复。仅在拆分确实能减少工作量时才委派，紧密耦合的
# 步骤保留在自己的上下文中完成。
DELEGATION_NOTE = (
    "\n\nAssess the scope of every request before acting. Handle small tasks "
    "yourself. When a task is substantial (for example multi-step research, "
    "long-form writing, deep analysis, or several independent subtasks), split "
    "it into focused subtasks and delegate them to the most suitable subagents "
    "listed in <available_subagents> with the use_subagent tool, then synthesize "
    "their final answers into one coherent reply. Delegate only when the split "
    "truly reduces effort, and keep tightly coupled steps in your own context."
)


def build_system_prompt() -> str:
    """返回主 agent 实际使用的系统提示词（用户配置 + 框架标签与委派说明）。"""
    return (
        f"{get_settings().agent_system_prompt}"
        f"{FRAMEWORK_CONTEXT_NOTE}"
        f"{DELEGATION_NOTE}"
    )


def build_subagent_system_prompt(prompt: str) -> str:
    """返回子 agent 的系统提示词（子 agent 配置的提示词 + 框架标签说明）。"""
    return f"{prompt}{FRAMEWORK_CONTEXT_NOTE}"
