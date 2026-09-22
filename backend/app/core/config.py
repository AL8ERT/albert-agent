"""应用配置：读取用户 JSON 配置与环境变量，并提供模型列表。

用户配置固定为四个顶层键（用户目录 .albert-agent/albert-agent-config.json），
完整结构由 UserConfig 模型定义（read_user_config 返回该模型，字段即文档）：
providers（模型列表）、mcpServers、subagents、webFetchAllowedDomains。
字段类型不匹配或出现空值时读取直接抛 RuntimeError（附校验详情），不静默跳过；
未知顶层键忽略；重复项（模型名 / 子 agent 名 / 域名）去重保留先出现的。
Settings 从环境变量与工作目录下的 .env 读取（优先级：环境变量 > .env > 默认值）。
模型列表与数据库连接串都从这里读取，供 agent、API 路由和持久化层共用。
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# 应用配置的目录名与文件名，固定放在用户主目录下
USER_CONFIG_DIRNAME = ".albert-agent"
USER_CONFIG_FILENAME = "albert-agent-config.json"

# 系统内置的通用任务子 agent；用户配置同名子 agent 时以用户配置为准。
DEFAULT_SUBAGENT_NAME = "general"
# 提示词译文：你是一个通用子 agent。使用可用的技能与工具独立完成委派的任务，
# 然后只返回最终答案。
DEFAULT_SUBAGENT_PROMPT = (
    "You are a general-purpose subagent. Complete the delegated task "
    "independently using the available skills and tools, then return only the "
    "final answer."
)


class ModelConfig(BaseModel):
    """单个模型的连接信息。"""

    name: str
    base_url: str
    api_key: str


class ProviderConfig(BaseModel):
    """单个模型 provider：url / api_key 与它提供的模型名列表。"""

    model_config = ConfigDict(extra="ignore")

    url: str = ""
    api_key: str = ""
    models: list[str] = Field(default_factory=list)

    @field_validator("models")
    @classmethod
    def _model_names_normalized(cls, value: list[str]) -> list[str]:
        """模型名去首尾空白；空白项视为无效配置。"""
        names = [name.strip() for name in value]
        if any(not name for name in names):
            raise ValueError("model names must be non-empty strings")
        return names


class SubagentConfig(BaseModel):
    """单个子 agent 的定义：名称 + 提示词（作为其系统提示词）。"""

    name: str
    prompt: str

    @field_validator("name", "prompt")
    @classmethod
    def _strip_nonempty(cls, value: str) -> str:
        """名称与提示词去首尾空白；空白视为无效配置。"""
        value = value.strip()
        if not value:
            raise ValueError("must be a non-empty string")
        return value


class UserConfig(BaseModel):
    """用户 JSON 配置的顶层结构（唯一事实来源，字段即文档）。

    字段名用 snake_case（PEP 8），JSON 键保持小驼峰（跟随 MCP 生态约定），
    通过 alias 对应；输入只认别名键。mcp_servers 的值为透传给 MCP 客户端的
    开放结构（stdio 用 command/args/env，远程用 url/headers，可带 type:
    http | sse），因此保留 dict[str, dict]。
    """

    model_config = ConfigDict(extra="ignore")

    providers: list[ProviderConfig] = Field(default_factory=list)
    mcp_servers: dict[str, dict[str, Any]] = Field(
        default_factory=dict, alias="mcpServers"
    )
    subagents: list[SubagentConfig] = Field(default_factory=list)
    web_fetch_allowed_domains: list[str] = Field(
        default_factory=list, alias="webFetchAllowedDomains"
    )

    @field_validator("web_fetch_allowed_domains")
    @classmethod
    def _domains_normalized(cls, value: list[str]) -> list[str]:
        """域名归一化：去空白、转小写、去前导点，去重保持顺序；空白项无效。"""
        domains: list[str] = []
        for item in value:
            domain = item.strip().lower().lstrip(".")
            if not domain:
                raise ValueError("domains must be non-empty strings")
            if domain not in domains:
                domains.append(domain)
        return domains

    def models(self) -> list[ModelConfig]:
        """把 providers 展开为模型列表；模型名全局去重，保留先出现的配置。"""
        models: list[ModelConfig] = []
        seen: set[str] = set()
        for provider in self.providers:
            for name in provider.models:
                if name in seen:
                    continue
                seen.add(name)
                models.append(
                    ModelConfig(
                        name=name, base_url=provider.url, api_key=provider.api_key
                    )
                )
        return models

    def subagents_deduped(self) -> list[SubagentConfig]:
        """同名子 agent 去重，保留先出现的。"""
        deduped: list[SubagentConfig] = []
        seen: set[str] = set()
        for subagent in self.subagents:
            if subagent.name in seen:
                continue
            seen.add(subagent.name)
            deduped.append(subagent)
        return deduped


def user_config_path() -> Path:
    """返回用户配置文件的完整路径（不保证文件存在）。"""
    return Path.home() / USER_CONFIG_DIRNAME / USER_CONFIG_FILENAME


def read_user_config() -> UserConfig:
    """读取并校验用户 JSON 配置；文件不存在时返回空配置。

    文件无法解析、顶层不是 JSON 对象、或字段不符合 UserConfig 结构时抛
    RuntimeError（附 Pydantic 校验详情），避免静默使用错误配置。
    """
    path = user_config_path()
    if not path.is_file():
        return UserConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read user config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"User config {path} must be a JSON object")
    try:
        return UserConfig.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid user config {path}: {exc}") from exc


@lru_cache
def get_user_config() -> UserConfig:
    """返回缓存的用户配置（首次访问时加载，修改配置后需重启后端）。"""
    return read_user_config()


class Settings(BaseSettings):
    """环境变量 / .env 中的全局配置项（优先级：环境变量 > .env > 默认值）。"""

    model_config = SettingsConfigDict(extra="ignore", env_file=".env")

    app_name: str = "Albert Agent API"
    cors_origins: list[str] = ["*"]

    # PostgreSQL 连接串；为空时 checkpointer 回退为内存实现
    database_url: str = ""

    # 默认系统提示词译文：你是 Albert，一个乐于助人且简洁的助手。
    agent_system_prompt: str = "You are Albert, a helpful and concise assistant."
    llm_temperature: float = 0.7


@lru_cache
def get_settings() -> Settings:
    """构建并缓存全局配置（环境变量 > .env > 默认值）。"""
    return Settings()


def get_models() -> list[ModelConfig]:
    """返回可用模型列表（providers 展开去重），未配置时为空列表（API 层返回 503）。"""
    return get_user_config().models()


def find_model(name: str) -> ModelConfig | None:
    """按模型名查找配置，找不到返回 None。"""
    for model in get_models():
        if model.name == name:
            return model
    return None


def get_mcp_servers() -> dict[str, dict[str, Any]]:
    """返回 MCP server 配置（键为名称，值为透传给 MCP 客户端的原始结构）。"""
    return dict(get_user_config().mcp_servers)


def get_subagents() -> tuple[SubagentConfig, ...]:
    """返回子 agent 列表：用户配置 + 内置默认（同名时用户配置优先）。

    内置的通用任务子 agent 始终可用；名单在进程内缓存，修改配置需重启后端。
    """
    configured = get_user_config().subagents_deduped()
    if any(subagent.name == DEFAULT_SUBAGENT_NAME for subagent in configured):
        return tuple(configured)
    return (
        *configured,
        SubagentConfig(name=DEFAULT_SUBAGENT_NAME, prompt=DEFAULT_SUBAGENT_PROMPT),
    )


def get_web_fetch_allowed_domains() -> tuple[str, ...]:
    """返回 web_fetch 域名白名单（已归一化；为空表示禁止访问任何地址）。"""
    return tuple(get_user_config().web_fetch_allowed_domains)
