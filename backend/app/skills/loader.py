"""技能加载：读取 ~/.albert-agent/skills/<name>/SKILL.md 的元数据。

目录约定：每个技能一个子目录，目录内 SKILL.md 用
YAML front matter 提供 name / description，正文是技能指令。本模块只负责
元数据（名称、描述、文件路径）；正文由模型需要时自行读取。
"""

from __future__ import annotations

import html
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.config import USER_CONFIG_DIRNAME

logger = logging.getLogger(__name__)

SKILLS_DIRNAME = "skills"
SKILL_FILE_NAME = "SKILL.md"


@dataclass(frozen=True)
class SkillMetadata:
    """技能的元数据；path 为 SKILL.md 的绝对路径。"""

    name: str
    description: str
    path: str


def skills_dir() -> Path:
    """返回用户技能目录（不保证存在）。"""
    return Path.home() / USER_CONFIG_DIRNAME / SKILLS_DIRNAME


def _split_front_matter(text: str) -> dict:
    """解析 SKILL.md 顶部的 YAML front matter；缺失或非法时返回空字典。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"),
        None,
    )
    if end is None:
        return {}
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def load_skills(root: Path | None = None) -> list[SkillMetadata]:
    """扫描技能目录并按名称排序返回元数据。

    目录不存在、子目录缺少 SKILL.md、或单个文件读取失败时都静默跳过；
    front matter 里没有 name 时回退为目录名。
    """
    base = root if root is not None else skills_dir()
    if not base.is_dir():
        return []

    skills: list[SkillMetadata] = []
    for child in sorted(base.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        skill_file = child / SKILL_FILE_NAME
        if not skill_file.is_file():
            continue
        try:
            text = skill_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Failed to read skill file %s", skill_file, exc_info=True)
            continue

        meta = _split_front_matter(text)
        name = str(meta.get("name") or child.name).strip() or child.name
        description = " ".join(str(meta.get("description") or "").split())
        skills.append(SkillMetadata(name=name, description=description, path=str(skill_file)))
    return skills


def _escape(value: str) -> str:
    """转义 XML 尖括号，防止技能名/描述伪造框架标签。"""
    return html.escape(value, quote=False)


def _format_skill_line(skill: SkillMetadata) -> str:
    suffix = f": {_escape(skill.description)}" if skill.description else ""
    return f"- {_escape(skill.name)}{suffix} (path: {_escape(skill.path)})"


def render_skills_section(skills: Iterable[SkillMetadata]) -> str:
    """渲染首轮注入系统提示词的 <available_skills> 段。"""
    items = list(skills)
    if not items:
        return ""
    lines = ["<available_skills>"]
    lines.extend(_format_skill_line(skill) for skill in items)
    lines.append("</available_skills>")
    return "\n".join(lines)


def render_skill_update(
    added: Iterable[SkillMetadata], removed: Iterable[str]
) -> str:
    """渲染后续轮次注入消息尾部的 <skill_update> 段（只含增删差分）。"""
    added_items = list(added)
    removed_items = list(removed)
    lines = ["<skill_update>"]
    if added_items:
        lines.append("Added skills:")
        lines.extend(_format_skill_line(skill) for skill in added_items)
    if removed_items:
        lines.append("Removed skills:")
        lines.extend(f"- {_escape(name)}" for name in removed_items)
    lines.append("</skill_update>")
    return "\n".join(lines)
