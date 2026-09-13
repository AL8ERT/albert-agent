"""应用配置：读取用户 JSON 配置与环境变量，并提供模型列表。

配置优先级（从高到低）：应用配置（用户目录 .albert-agent/albert-agent-config.json）> 环境变量 > 代码默认值。
数据库连接串额外支持工作目录下的 .env（只读其中的 DATABASE_URL，其他配置一律不读 .env）。
模型列表与数据库连接串都从这里读取，供 agent、API 路由和持久化层共用。
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

# 应用配置的目录名与文件名，固定放在用户主目录下
USER_CONFIG_DIRNAME = ".albert-agent"
USER_CONFIG_FILENAME = "albert-agent-config.json"

# MCP server 配置在用户 JSON 里的键名，兼容 camelCase 与下划线/中划线写法。
_MCP_SERVER_KEYS = ("mcpServers", "mcp_servers", "mcp-servers", "mcpservers")

# 子 agent 配置在用户 JSON 里的键名，兼容 camelCase 与下划线/中划线写法。
_SUBAGENT_KEYS = ("subagents", "sub_agents", "sub-agents")

# 系统内置的通用任务子 agent；用户配置同名子 agent 时以用户配置为准。
DEFAULT_SUBAGENT_NAME = "general"
DEFAULT_SUBAGENT_PROMPT = (
    "You are a general-purpose subagent. Complete the delegated task "
    "independently using the available skills and tools, then return only "
    "the final answer."
)

# web_fetch 可访问域名白名单在用户 JSON 里的键名（字符串数组）。
_WEB_FETCH_DOMAIN_KEYS = (
    "webFetchAllowedDomains",
    "web_fetch_allowed_domains",
    "web-fetch-allowed-domains",
)

# 用户配置文件里的键名别名 -> Settings 字段名。
# 兼容多种历史写法（url / model-name / api-key / db_url 等），统一归一化后再交给 pydantic。
_USER_CONFIG_KEYS = {
    "url": "deepseek_base_url",
    "base_url": "deepseek_base_url",
    "base-url": "deepseek_base_url",
    "model_name": "deepseek_model",
    "model-name": "deepseek_model",
    "model": "deepseek_model",
    "api_key": "deepseek_api_key",
    "api-key": "deepseek_api_key",
    "apikey": "deepseek_api_key",
    "database_url": "database_url",
    "database-url": "database_url",
    "db_url": "database_url",
    "pg_url": "database_url",
}


class ModelConfig(BaseModel):
    """单个模型的连接信息。"""

    name: str
    base_url: str
    api_key: str


class SubagentConfig(BaseModel):
    """单个子 agent 的定义：名称 + 提示词（作为其系统提示词）。"""

    name: str
    prompt: str


def user_config_path() -> Path:
    """返回用户配置文件的完整路径（不保证文件存在）。"""
    return Path.home() / USER_CONFIG_DIRNAME / USER_CONFIG_FILENAME


def read_user_config() -> dict[str, Any]:
    """读取用户 JSON 配置文件；文件不存在时返回空字典。

    文件存在但无法解析、或顶层不是 JSON 对象时抛 RuntimeError，
    避免静默使用错误配置。
    """
    path = user_config_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read user config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"User config {path} must be a JSON object")
    return raw


def load_user_config() -> dict[str, Any]:
    """把用户配置里的键名映射为 Settings 字段名，并过滤空值。

    只有出现在 _USER_CONFIG_KEYS 里的键会被采纳，其余键（如 models 列表）由
    _models_from_raw 单独处理。
    """
    raw = read_user_config()
    values: dict[str, Any] = {}
    for key, value in raw.items():
        field = _USER_CONFIG_KEYS.get(key.strip().lower())
        if field is not None and value not in (None, ""):
            values[field] = value
    return values


def _as_text(value: Any) -> str:
    """把配置值统一转成字符串，None / 空串返回空字符串。"""
    return str(value) if value not in (None, "") else ""


def _models_from_providers(providers: list[Any]) -> list[ModelConfig]:
    """解析 providers 结构：每个 provider 提供自己的 url / api_key 与模型列表。

    models 必须是字符串列表，非字符串项忽略；模型名全局去重，保留先出现的配置。
    """
    models: list[ModelConfig] = []
    seen: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        provider_url = _as_text(provider.get("url") or provider.get("base_url"))
        provider_key = _as_text(provider.get("api_key") or provider.get("api-key"))
        entries = provider.get("models")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, str):
                continue
            name = entry.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            models.append(
                ModelConfig(name=name, base_url=provider_url, api_key=provider_key)
            )
    return models


def _models_from_raw(raw: dict[str, Any]) -> list[ModelConfig]:
    """从应用配置的原始 JSON 中解析模型列表（仅支持 providers 结构）。"""
    providers = raw.get("providers")
    if not isinstance(providers, list):
        return []
    return _models_from_providers(providers)


class Settings(BaseSettings):
    """环境变量中的全局配置项。"""

    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "Albert Agent API"
    cors_origins: list[str] = ["*"]

    # 未配置用户 JSON 时的模型回退配置
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    # PostgreSQL 连接串；为空时 checkpointer 回退到内存实现
    database_url: str = ""

    agent_system_prompt: str = "You are Albert, a helpful and concise assistant."
    llm_temperature: float = 0.7


# .env 中唯一被读取的键
_DOTENV_DATABASE_KEY = "DATABASE_URL"


def _read_dotenv_database_url() -> str:
    """从工作目录的 .env 中读取 DATABASE_URL，其他键一律忽略。

    简单的 KEY=VALUE 解析：支持引号包裹的值、忽略空行与 # 注释；
    文件不存在或读取失败时返回空字符串。
    """
    path = Path(".env")
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    prefix = f"{_DOTENV_DATABASE_KEY}="
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value
    return ""


@lru_cache
def get_settings() -> Settings:
    """构建并缓存全局配置（用户 JSON > 环境变量 > .env 中的 DATABASE_URL）。"""
    settings = Settings(**load_user_config())
    if not settings.database_url:
        settings.database_url = _read_dotenv_database_url()
    return settings


@lru_cache
def get_models() -> list[ModelConfig]:
    """返回可用模型列表，并缓存结果。

    优先使用用户 JSON 中的模型定义；若没有，则回退到环境变量中的
    单个 DeepSeek 配置；两者都没有时返回空列表（API 层会返回 503）。
    """
    models = _models_from_raw(read_user_config())
    if models:
        return models
    settings = get_settings()
    if settings.deepseek_api_key:
        return [
            ModelConfig(
                name=settings.deepseek_model,
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
            )
        ]
    return []


def find_model(name: str) -> ModelConfig | None:
    """按模型名查找配置，找不到返回 None。"""
    for model in get_models():
        if model.name == name:
            return model
    return None


def read_mcp_servers(raw: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """从用户配置 JSON 中读取 MCP server 定义（未配置时返回空字典）。

    server 配置采用通用写法：stdio 用 command/args/env，远程用
    url/headers（可带 type: http | sse）。键名支持 mcpServers /
    mcp_servers / mcp-servers / mcpservers。
    """
    source = read_user_config() if raw is None else raw
    for key in _MCP_SERVER_KEYS:
        value = source.get(key)
        if isinstance(value, dict):
            return {
                str(name): dict(server)
                for name, server in value.items()
                if isinstance(server, dict)
            }
    return {}


@lru_cache
def get_mcp_servers() -> dict[str, dict[str, Any]]:
    """返回缓存的 MCP server 配置（启动时加载，修改配置需重启）。"""
    return read_mcp_servers()


def read_subagents(raw: dict[str, Any] | None = None) -> list[SubagentConfig]:
    """从用户配置 JSON 中读取子 agent 定义（对象数组，每项 name + prompt）。

    只接受 name / prompt 都是非空字符串的项；同名子 agent 去重，保留先出现者。
    键名支持 subagents / sub_agents / sub-agents。
    """
    source = read_user_config() if raw is None else raw
    for key in _SUBAGENT_KEYS:
        value = source.get(key)
        if not isinstance(value, list):
            continue
        subagents: list[SubagentConfig] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            prompt = item.get("prompt")
            if not isinstance(name, str) or not isinstance(prompt, str):
                continue
            name = name.strip()
            prompt = prompt.strip()
            if not name or not prompt or name in seen:
                continue
            seen.add(name)
            subagents.append(SubagentConfig(name=name, prompt=prompt))
        return subagents
    return []


@lru_cache
def get_subagents() -> tuple[SubagentConfig, ...]:
    """返回缓存的子 agent 列表：用户配置 + 内置默认（同名时用户配置优先）。

    内置的通用任务子 agent 始终可用；修改配置需重启后端。
    """
    configured = read_subagents()
    if any(subagent.name == DEFAULT_SUBAGENT_NAME for subagent in configured):
        return tuple(configured)
    return (
        *configured,
        SubagentConfig(name=DEFAULT_SUBAGENT_NAME, prompt=DEFAULT_SUBAGENT_PROMPT),
    )


def read_web_fetch_allowed_domains(raw: dict[str, Any] | None = None) -> list[str]:
    """读取 web_fetch 域名白名单（字符串数组），归一化为小写并去掉前导点。

    只接受字符串项，重复项去重并保持顺序；未配置时返回空列表（= 全部拒绝）。
    """
    source = read_user_config() if raw is None else raw
    for key in _WEB_FETCH_DOMAIN_KEYS:
        value = source.get(key)
        if not isinstance(value, list):
            continue
        domains: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            domain = item.strip().lower().lstrip(".")
            if domain and domain not in domains:
                domains.append(domain)
        return domains
    return []


@lru_cache
def get_web_fetch_allowed_domains() -> tuple[str, ...]:
    """返回缓存的 web_fetch 域名白名单（为空表示禁止访问任何地址）。"""
    return tuple(read_web_fetch_allowed_domains())
