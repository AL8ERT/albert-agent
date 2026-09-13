"""子 agent 中间件：把可用子 agent 名单以隐藏 HumanMessage 注入对话。

与 SkillMiddleware 相同的策略：
- 首轮：把完整名单渲染成 <available_subagents>，作为带 ``hide_from_chat``
  标记的 HumanMessage 追加到消息尾部并持久化；
- 后续轮次：对比当前配置与已公告名单，把增删差分渲染成 <subagent_update>
  HumanMessage 追加到尾部；无变化时不注入。
"""

from __future__ import annotations

import logging
from typing import NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.core.config import SubagentConfig
from app.subagents.loader import (
    SubagentLoader,
    load_subagents,
    render_subagent_update,
    render_subagents_section,
)

logger = logging.getLogger(__name__)


class SubagentState(AgentState):
    """在 AgentState 上扩展已公告子 agent 名单；None 表示首轮尚未公告。"""

    announced_subagents: NotRequired[list[str]]


class SubagentMiddleware(AgentMiddleware):
    """负责首轮全量注入与后续增删差分。"""

    state_schema = SubagentState

    def __init__(self, loader: SubagentLoader = load_subagents) -> None:
        super().__init__()
        self._loader = loader

    def _snapshot(self) -> list[SubagentConfig]:
        """读取当前子 agent 快照；读取失败时退化为空列表而不是中断对话。"""
        try:
            return self._loader()
        except Exception:
            logger.exception("Failed to load subagents")
            return []

    @staticmethod
    def _hidden_message(content: str) -> HumanMessage:
        return HumanMessage(
            content=content, additional_kwargs={"hide_from_chat": True}
        )

    def before_model(self, state, runtime):
        current = self._snapshot()
        current_names = {subagent.name for subagent in current}
        announced = state.get("announced_subagents")

        if announced is None:
            # 首轮：没有子 agent 也要落一个空名单，后续才能走差分逻辑
            if not current:
                return {"announced_subagents": []}
            logger.info("Announcing %d subagent(s) on first turn", len(current))
            return {
                "messages": [
                    self._hidden_message(render_subagents_section(current))
                ],
                "announced_subagents": sorted(current_names),
            }

        previous = set(announced)
        added = [
            subagent for subagent in current if subagent.name not in previous
        ]
        removed = sorted(previous - current_names)
        if not added and not removed:
            return None

        logger.info(
            "Subagent changes detected: added=%s removed=%s",
            [subagent.name for subagent in added],
            removed,
        )
        return {
            "messages": [
                self._hidden_message(render_subagent_update(added, removed))
            ],
            "announced_subagents": sorted(current_names),
        }

    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)
