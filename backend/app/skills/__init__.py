"""技能系统：从用户目录加载 SKILL.md 元数据，并在对话中增量注入。"""

from app.skills.loader import (
    SKILL_FILE_NAME,
    SKILLS_DIRNAME,
    SkillMetadata,
    load_skills,
    render_skill_update,
    render_skills_section,
    skills_dir,
)

__all__ = [
    "SKILLS_DIRNAME",
    "SKILL_FILE_NAME",
    "SkillMetadata",
    "load_skills",
    "render_skills_section",
    "render_skill_update",
    "skills_dir",
]
