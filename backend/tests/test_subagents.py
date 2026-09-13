"""子 agent 系统测试：渲染与中间件注入时机（配置解析见 test_config.py）。"""

from app.core.config import SubagentConfig
from app.subagents.loader import render_subagent_update, render_subagents_section
from app.subagents.middleware import SubagentMiddleware


def test_render_subagents_section_lists_name_and_prompt() -> None:
    subagents = [
        SubagentConfig(name="researcher", prompt="Find facts\nand cite them"),
        SubagentConfig(name="writer", prompt="Write prose"),
    ]

    section = render_subagents_section(subagents)

    assert section.startswith("<available_subagents>")
    assert "- researcher: Find facts and cite them" in section
    assert "- writer: Write prose" in section
    assert render_subagents_section([]) == ""


def test_render_subagents_section_escapes_tags() -> None:
    subagent = SubagentConfig(name="x", prompt="<script>alert(1)</script>")

    section = render_subagents_section([subagent])

    assert "&lt;script&gt;" in section


def test_render_subagent_update_only_contains_diff() -> None:
    added = SubagentConfig(name="new", prompt="New prompt")

    update = render_subagent_update([added], ["old"])

    assert "Added subagents:" in update
    assert "- new: New prompt" in update
    assert "Removed subagents:" in update
    assert "- old" in update
    # 没变化的两边都不出现
    assert (
        render_subagent_update([], []).strip()
        == "<subagent_update>\n</subagent_update>"
    )


def test_before_model_announces_full_section_on_first_turn() -> None:
    subagents = [
        SubagentConfig(name="general", prompt="General tasks"),
        SubagentConfig(name="research", prompt="Research tasks"),
    ]
    middleware = SubagentMiddleware(loader=lambda: subagents)

    update = middleware.before_model({"announced_subagents": None}, None)

    assert update is not None
    assert update["announced_subagents"] == ["general", "research"]
    (message,) = update["messages"]
    assert message.content.startswith("<available_subagents>")
    assert "- general" in message.content and "- research" in message.content
    assert message.additional_kwargs.get("hide_from_chat") is True


def test_before_model_freezes_empty_roster_on_first_turn() -> None:
    """首轮没有子 agent 时也要落空名单，后续才能检测到新增。"""
    middleware = SubagentMiddleware(loader=lambda: [])

    assert middleware.before_model({}, None) == {"announced_subagents": []}


def test_before_model_emits_diff_message() -> None:
    current = [
        SubagentConfig(name="new", prompt="N"),
        SubagentConfig(name="keep", prompt="K"),
    ]
    middleware = SubagentMiddleware(loader=lambda: current)

    update = middleware.before_model(
        {"announced_subagents": ["keep", "old"]}, None
    )

    assert update is not None
    assert update["announced_subagents"] == ["keep", "new"]
    (message,) = update["messages"]
    assert message.content.startswith("<subagent_update>")
    assert "Added subagents:" in message.content
    assert "- new: N" in message.content
    assert "Removed subagents:" in message.content
    assert "- old" in message.content
    assert message.additional_kwargs.get("hide_from_chat") is True


def test_before_model_noop_when_unchanged() -> None:
    subagent = SubagentConfig(name="general", prompt="General")
    middleware = SubagentMiddleware(loader=lambda: [subagent])

    assert middleware.before_model({"announced_subagents": ["general"]}, None) is None


def test_before_model_survives_loader_failure() -> None:
    """配置读取失败时不抛错，按空快照处理。"""

    def broken_loader() -> list[SubagentConfig]:
        raise OSError("boom")

    middleware = SubagentMiddleware(loader=broken_loader)

    assert middleware.before_model({"announced_subagents": None}, None) == {
        "announced_subagents": []
    }
