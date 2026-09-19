"""配置加载测试：用户 JSON、环境变量与模型解析。

每个用例前后清空 lru_cache，保证测试之间不共享已缓存的配置。
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core import config


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    """进入/退出每个用例时清空 Settings 与用户配置缓存。"""
    config.get_settings.cache_clear()
    config.get_user_config.cache_clear()
    yield
    config.get_settings.cache_clear()
    config.get_user_config.cache_clear()


def test_user_config_path_points_to_app_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认配置路径应为 用户主目录/.albert-agent/albert-agent-config.json。"""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert config.user_config_path() == (
        tmp_path / ".albert-agent" / "albert-agent-config.json"
    )


def test_read_user_config_missing_file_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配置文件不存在时返回空的 UserConfig（各字段为默认值）。"""
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")

    assert config.read_user_config() == config.UserConfig()


def test_read_user_config_parses_all_sections_and_ignores_unknown_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """四个顶层键全部解析为 UserConfig 字段，未知顶层键忽略。"""
    payload = {
        "unknown": {"ignored": True},
        "providers": [
            {"url": "https://a.example/v1", "api_key": "sk-a", "models": ["m-1"]}
        ],
        "mcpServers": {"playwright": {"command": "npx"}},
        "subagents": [{"name": "researcher", "prompt": "Find facts"}],
        "webFetchAllowedDomains": ["Example.COM"],
    }
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    user_config = config.read_user_config()

    assert isinstance(user_config, config.UserConfig)
    assert user_config.providers[0].url == "https://a.example/v1"
    assert user_config.providers[0].models == ["m-1"]
    assert user_config.mcp_servers == {"playwright": {"command": "npx"}}
    assert [(s.name, s.prompt) for s in user_config.subagents] == [
        ("researcher", "Find facts")
    ]
    assert user_config.web_fetch_allowed_domains == ["example.com"]


def test_get_models_ignores_legacy_flat_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """旧版顶层 models 列表不再解析，只有 providers 结构生效。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"models": ["deepseek-chat", "deepseek-reasoner"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert config.get_models() == []


def test_dotenv_provides_all_settings_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 可提供全部 Settings 字段（pydantic-settings 读取）。"""
    (tmp_path / ".env").write_text(
        "APP_NAME=Dotenv App\n"
        "LLM_TEMPERATURE=0.1\n"
        "DATABASE_URL=postgresql://u:p@localhost:5432/db\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = config.get_settings()

    assert settings.app_name == "Dotenv App"
    assert settings.llm_temperature == 0.1
    assert settings.database_url == "postgresql://u:p@localhost:5432/db"


def test_database_url_env_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DATABASE_URL 优先级：环境变量 > .env。"""
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://dotenv/db\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://env/db")

    assert config.get_settings().database_url == "postgresql://env/db"


def test_get_models_from_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """providers 结构：每个 provider 的 url/api_key 独立，模型挂在自己下面。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "url": "https://api.deepseek.com",
                        "api_key": "sk-ds",
                        "models": ["deepseek-flash", "deepseek-reasoner"],
                    },
                    {
                        "url": "https://api.openai.com/v1",
                        "api_key": "sk-oa",
                        "models": ["gpt-4o", "gpt-4o-mini"],
                    },
                    {"url": "https://third.example/v1", "models": ["solo-model"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    models = config.get_models()

    assert [(m.name, m.base_url, m.api_key) for m in models] == [
        ("deepseek-flash", "https://api.deepseek.com", "sk-ds"),
        ("deepseek-reasoner", "https://api.deepseek.com", "sk-ds"),
        ("gpt-4o", "https://api.openai.com/v1", "sk-oa"),
        ("gpt-4o-mini", "https://api.openai.com/v1", "sk-oa"),
        ("solo-model", "https://third.example/v1", ""),
    ]


def test_get_models_from_providers_dedupes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型名跨 provider 去重（保留先出现的）。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "url": "https://a.example/v1",
                        "api_key": "sk-a",
                        "models": ["shared"],
                    },
                    {
                        "url": "https://b.example/v1",
                        "api_key": "sk-b",
                        "models": ["shared", "only-b"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    models = config.get_models()

    assert [(m.name, m.base_url, m.api_key) for m in models] == [
        ("shared", "https://a.example/v1", "sk-a"),
        ("only-b", "https://b.example/v1", "sk-b"),
    ]


def test_get_models_providers_malformed_entry_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """providers 里的坏条目（非对象项、models 非列表、非字符串/空白模型名）直接报错。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "providers": [
                    "not-a-provider",
                    {"url": "https://a.example/v1"},
                    {"url": "https://b.example/v1", "models": "solo-model"},
                    {"url": "https://c.example/v1", "models": [123, ""]},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    with pytest.raises(RuntimeError, match="Invalid user config"):
        config.get_models()


def test_get_mcp_servers_reads_camel_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mcpServers 键（标准 MCP 客户端写法）应被解析。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "playwright": {
                        "command": "npx",
                        "args": ["-y", "@playwright/mcp@latest"],
                        "enabled": True,
                    },
                    "remote": {"url": "https://mcp.example.com/mcp", "type": "http"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    servers = config.get_mcp_servers()

    assert set(servers) == {"playwright", "remote"}
    assert servers["playwright"]["command"] == "npx"
    assert servers["remote"]["url"] == "https://mcp.example.com/mcp"


def test_get_mcp_servers_malformed_entry_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mcpServers 的值不是对象时直接报错。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"mcpServers": {"broken": "not-an-object"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    with pytest.raises(RuntimeError, match="Invalid user config"):
        config.get_mcp_servers()


def test_get_mcp_servers_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没有 MCP 配置时返回空字典。"""
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")

    assert config.get_mcp_servers() == {}


def test_get_subagents_includes_builtin_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没有用户配置时也应有内置的 general 通用任务子 agent。"""
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")

    subagents = config.get_subagents()

    assert [subagent.name for subagent in subagents] == [
        config.DEFAULT_SUBAGENT_NAME
    ]
    assert subagents[0].prompt == config.DEFAULT_SUBAGENT_PROMPT


def test_get_subagents_reads_config_and_appends_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户配置的子 agent 在前，内置默认子 agent 追加在后。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "subagents": [
                    {"name": "researcher", "prompt": "Find facts"},
                    {"name": "writer", "prompt": "Write prose"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    subagents = config.get_subagents()

    assert [subagent.name for subagent in subagents] == [
        "researcher",
        "writer",
        "general",
    ]
    assert subagents[0].prompt == "Find facts"


def test_get_subagents_custom_general_overrides_builtin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户配置了同名 general 子 agent 时，以内置名对应的用户配置为准。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"subagents": [{"name": "general", "prompt": "Custom"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    subagents = config.get_subagents()

    assert [(subagent.name, subagent.prompt) for subagent in subagents] == [
        ("general", "Custom")
    ]


def test_get_subagents_strips_and_dedupes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """name/prompt 去首尾空白；同名子 agent 只保留先出现的。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "subagents": [
                    {"name": "ok", "prompt": "  do it  "},
                    {"name": "ok", "prompt": "duplicate"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    subagents = config.get_subagents()

    assert [(subagent.name, subagent.prompt) for subagent in subagents] == [
        ("ok", "do it"),
        ("general", config.DEFAULT_SUBAGENT_PROMPT),
    ]


def test_get_subagents_malformed_entry_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subagents 里的坏条目（缺字段、空名称、非字符串）直接报错。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "subagents": [
                    {"name": "no-prompt"},
                    {"name": "", "prompt": "x"},
                    {"name": 123, "prompt": "bad-name"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    with pytest.raises(RuntimeError, match="Invalid user config"):
        config.get_subagents()


def test_get_subagents_non_list_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subagents 不是数组时直接报错。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"subagents": {"name": "x", "prompt": "y"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    with pytest.raises(RuntimeError, match="Invalid user config"):
        config.get_subagents()


def test_get_web_fetch_allowed_domains_normalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """白名单应转小写、去前导点、去重并保持顺序。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "webFetchAllowedDomains": [
                    "Example.com",
                    ".docs.python.org",
                    "example.com",
                    "  github.com  ",
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert config.get_web_fetch_allowed_domains() == (
        "example.com",
        "docs.python.org",
        "github.com",
    )


@pytest.mark.parametrize("domains", [[123], [""]])
def test_get_web_fetch_allowed_domains_malformed_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    domains: list,
) -> None:
    """白名单出现非字符串项或空白项时直接报错。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"webFetchAllowedDomains": domains}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    with pytest.raises(RuntimeError, match="Invalid user config"):
        config.get_web_fetch_allowed_domains()


def test_get_web_fetch_allowed_domains_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未配置白名单时返回空元组（调用方按全部拒绝处理）。"""
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")

    assert config.get_web_fetch_allowed_domains() == ()
