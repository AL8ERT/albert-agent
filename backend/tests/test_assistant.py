"""agent 工厂测试：验证 create_agent 挂载了共享的 checkpointer。"""

from pytest import MonkeyPatch

from app.agents import assistant
from app.agents.prompts import build_subagent_system_prompt
from app.core.config import ModelConfig


def test_get_agent_wires_shared_checkpointer(monkeypatch: MonkeyPatch) -> None:
    """get_agent 创建的 agent 必须使用全局 checkpointer（多轮对话依赖它）。"""
    # 用假配置绕过真实模型查找，避免依赖用户配置 / API Key
    monkeypatch.setattr(
        assistant,
        "find_model",
        lambda name: ModelConfig(
            name=name,
            base_url="https://example.com",
            api_key="sk-test",
        ),
    )

    agent = assistant.get_agent("checkpointer-test-model")

    assert agent.checkpointer is assistant.get_checkpointer()


def test_build_system_prompt_declares_framework_tags() -> None:
    """系统提示词必须声明框架注入标签的权威性。"""
    prompt = assistant.build_system_prompt()

    assert "<available_skills>" in prompt
    assert "<skill_update>" in prompt
    assert "<available_subagents>" in prompt
    assert "<subagent_update>" in prompt


def test_build_system_prompt_instructs_task_assessment_and_delegation() -> None:
    """主 agent 系统提示词必须要求评估任务量，重大任务拆分给子 agent。"""
    prompt = assistant.build_system_prompt()

    assert "Assess the scope" in prompt
    assert "delegate" in prompt
    assert "use_subagent" in prompt


def test_build_system_prompt_instructs_todolist_usage() -> None:
    """主 agent 系统提示词必须要求复杂任务借助 todolist 工具开展工作。"""
    prompt = assistant.build_system_prompt()

    assert "todolist" in prompt
    # 主动触发阈值与整表替换语义
    assert "3 or more distinct steps" in prompt
    assert "replaces the whole list" in prompt
    # 状态维护规则：单一进行中、完成判定、阻塞处理
    assert "only one item in_progress" in prompt
    assert "never batch completions" in prompt
    assert "follow-up item describing the blocker" in prompt


def test_build_subagent_system_prompt_keeps_configured_prompt() -> None:
    """子 agent 系统提示词应保留配置的提示词并附框架说明。"""
    prompt = build_subagent_system_prompt("You are a research subagent.")

    assert prompt.startswith("You are a research subagent.")
    assert "<available_subagents>" in prompt


def test_build_subagent_system_prompt_has_no_delegation_note() -> None:
    """子 agent 不能再调用子 agent，不应注入任务委派说明。"""
    prompt = build_subagent_system_prompt("You are a research subagent.")

    assert "Assess the scope" not in prompt
    assert "use_subagent" not in prompt


def test_build_subagent_system_prompt_has_no_todolist_note() -> None:
    """子 agent 不挂载 todolist 工具，不应注入待办事项说明。"""
    prompt = build_subagent_system_prompt("You are a research subagent.")

    assert "todolist" not in prompt
