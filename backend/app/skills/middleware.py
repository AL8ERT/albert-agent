"""技能中间件：把技能元数据以隐藏 HumanMessage 注入对话，并增量同步变化。

- 首轮：把完整技能清单渲染成 <available_skills>，作为一条带 ``hide_from_chat``
  标记的 HumanMessage 追加到消息尾部并持久化进 checkpointer；之后所有轮次都能
  在历史里看到它，系统提示词保持完全静态（前缀缓存稳定）。
- 后续轮次：每次模型调用前对比当前技能目录与已公告名单，把新增技能的元数据和
  被删除的技能名合并成一条 <skill_update> HumanMessage 追加到尾部。

隐藏消息只影响前端展示：正常对话视图看不到（前端只渲染 SSE token 与用户输入），
「查看消息」面板仍会展示它。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.skills.loader import (
    SkillMetadata,
    load_skills,
    render_skill_update,
    render_skills_section,
)

logger = logging.getLogger(__name__)

SkillLoader = Callable[[], list[SkillMetadata]]


class SkillState(AgentState):
    """在 AgentState 上扩展已公告技能名单；None 表示首轮尚未公告。"""

    announced_skills: NotRequired[list[str]]


class SkillMiddleware(AgentMiddleware):
    """负责首轮全量注入与后续增删差分。"""

    state_schema = SkillState

    def __init__(self, loader: SkillLoader = load_skills) -> None:
        super().__init__()
        self._loader = loader

    def _snapshot(self) -> list[SkillMetadata]:
        """读取当前技能快照；读取失败时退化为空列表而不是中断对话。"""
        try:
            return self._loader()
        except Exception:
            logger.exception("Failed to load skills")
            return []

    @staticmethod
    def _hidden_message(content: str) -> HumanMessage:
        return HumanMessage(
            content=content, additional_kwargs={"hide_from_chat": True}
        )

    def before_model(self, state, runtime):
        current = self._snapshot()
        current_names = {skill.name for skill in current}
        announced = state.get("announced_skills")

        if announced is None:
            # 首轮：没有技能也要落一个空名单，后续才能走差分逻辑
            if not current:
                return {"announced_skills": []}
            logger.info("Announcing %d skill(s) on first turn", len(current))
            return {
                "messages": [self._hidden_message(render_skills_section(current))],
                "announced_skills": sorted(current_names),
            }

        previous = set(announced)
        added = [skill for skill in current if skill.name not in previous]
        removed = sorted(previous - current_names)
        if not added and not removed:
            return None

        logger.info(
            "Skill changes detected: added=%s removed=%s",
            [skill.name for skill in added],
            removed,
        )
        return {
            "messages": [self._hidden_message(render_skill_update(added, removed))],
            "announced_skills": sorted(current_names),
        }

    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)
