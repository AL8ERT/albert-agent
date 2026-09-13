"""技能系统测试：SKILL.md 元数据加载、渲染与中间件注入时机。"""

from pathlib import Path

from app.skills.loader import (
    SkillMetadata,
    load_skills,
    render_skill_update,
    render_skills_section,
)
from app.skills.middleware import SkillMiddleware


def _write_skill(
    root: Path,
    name: str,
    body: str = "skill body",
    *,
    description: str | None = None,
    file_name: str = "SKILL.md",
) -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    front = (
        f"---\nname: {name}\ndescription: {description}\n---\n"
        if description is not None
        else ""
    )
    path = skill_dir / file_name
    path.write_text(front + body, encoding="utf-8")
    return path


def test_load_skills_reads_frontmatter(tmp_path: Path) -> None:
    _write_skill(tmp_path, "pdf", description="Process PDF files")
    _write_skill(tmp_path, "zip", description="Handle archives")

    skills = load_skills(tmp_path)

    assert [(skill.name, skill.description) for skill in skills] == [
        ("pdf", "Process PDF files"),
        ("zip", "Handle archives"),
    ]
    assert skills[0].path.endswith("SKILL.md")


def test_load_skills_falls_back_to_directory_name(tmp_path: Path) -> None:
    """没有 front matter 时用目录名作为技能名。"""
    _write_skill(tmp_path, "plain")

    skills = load_skills(tmp_path)

    assert [(skill.name, skill.description) for skill in skills] == [("plain", "")]


def test_load_skills_skips_missing_and_incomplete(tmp_path: Path) -> None:
    (tmp_path / "empty-dir").mkdir()
    _write_skill(tmp_path, "other", file_name="README.md")
    _write_skill(tmp_path, "ok", description="fine")

    assert [skill.name for skill in load_skills(tmp_path)] == ["ok"]
    assert load_skills(tmp_path / "missing") == []


def test_render_skills_section_escapes_tags() -> None:
    skill = SkillMetadata(
        name="pdf",
        description="<script>alert(1)</script>",
        path="/skills/pdf/SKILL.md",
    )

    section = render_skills_section([skill])

    assert section.startswith("<available_skills>")
    assert "&lt;script&gt;" in section
    assert render_skills_section([]) == ""


def test_render_skill_update_only_contains_diff() -> None:
    added = SkillMetadata(name="new", description="New skill", path="/s/new/SKILL.md")

    update = render_skill_update([added], ["old"])

    assert "Added skills:" in update
    assert "- new: New skill" in update
    assert "Removed skills:" in update
    assert "- old" in update
    # 没变化的两边都不出现
    assert render_skill_update([], []).strip() == "<skill_update>\n</skill_update>"


def test_before_model_announces_full_section_on_first_turn() -> None:
    skills = [
        SkillMetadata(name="pdf", description="PDF", path="/s/pdf/SKILL.md"),
        SkillMetadata(name="zip", description="ZIP", path="/s/zip/SKILL.md"),
    ]
    middleware = SkillMiddleware(loader=lambda: skills)

    update = middleware.before_model({"announced_skills": None}, None)

    assert update is not None
    assert update["announced_skills"] == ["pdf", "zip"]
    (message,) = update["messages"]
    assert message.content.startswith("<available_skills>")
    assert "- pdf" in message.content and "- zip" in message.content
    assert message.additional_kwargs.get("hide_from_chat") is True


def test_before_model_freezes_empty_roster_on_first_turn() -> None:
    """首轮没有技能时也要落空名单，后续才能检测到新增。"""
    middleware = SkillMiddleware(loader=lambda: [])

    assert middleware.before_model({}, None) == {"announced_skills": []}


def test_before_model_emits_diff_message() -> None:
    current = [
        SkillMetadata(name="new", description="N", path="/s/new/SKILL.md"),
        SkillMetadata(name="keep", description="K", path="/s/keep/SKILL.md"),
    ]
    middleware = SkillMiddleware(loader=lambda: current)

    update = middleware.before_model({"announced_skills": ["keep", "old"]}, None)

    assert update is not None
    assert update["announced_skills"] == ["keep", "new"]
    (message,) = update["messages"]
    assert message.content.startswith("<skill_update>")
    assert "Added skills:" in message.content
    assert "- new" in message.content
    assert "Removed skills:" in message.content
    assert "- old" in message.content
    assert message.additional_kwargs.get("hide_from_chat") is True


def test_before_model_noop_when_unchanged() -> None:
    skill = SkillMetadata(name="pdf", description="PDF", path="/s/pdf/SKILL.md")
    middleware = SkillMiddleware(loader=lambda: [skill])

    assert middleware.before_model({"announced_skills": ["pdf"]}, None) is None


def test_before_model_survives_loader_failure() -> None:
    """技能目录读取失败时不抛错，按空快照处理。"""

    def broken_loader() -> list[SkillMetadata]:
        raise OSError("boom")

    middleware = SkillMiddleware(loader=broken_loader)

    assert middleware.before_model({"announced_skills": None}, None) == {
        "announced_skills": []
    }
