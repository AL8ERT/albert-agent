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
    """进入/退出每个用例时清空 Settings / models / mcp / subagents / web_fetch 缓存。"""
    config.get_settings.cache_clear()
    config.get_models.cache_clear()
    config.get_mcp_servers.cache_clear()
    config.get_subagents.cache_clear()
    config.get_web_fetch_allowed_domains.cache_clear()
    yield
    config.get_settings.cache_clear()
    config.get_models.cache_clear()
    config.get_mcp_servers.cache_clear()
    config.get_subagents.cache_clear()
    config.get_web_fetch_allowed_domains.cache_clear()


def test_user_config_path_points_to_app_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认配置路径应为 用户主目录/.albert-agent/albert-agent-config.json。"""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    assert config.user_config_path() == (
        tmp_path / ".albert-agent" / "albert-agent-config.json"
    )


def test_load_user_config_maps_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户配置里的多种键名别名应归一化为 Settings 字段名。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "url": "https://example.com/v1",
                "model-name": "my-model",
                "api-key": "sk-test",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert config.load_user_config() == {
        "deepseek_base_url": "https://example.com/v1",
        "deepseek_model": "my-model",
        "deepseek_api_key": "sk-test",
    }


def test_load_user_config_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配置文件不存在时返回空字典（不抛错）。"""
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")

    assert config.load_user_config() == {}


def test_load_user_config_maps_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """db_url 别名应映射到 database_url。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"db_url": "postgresql://u:p@localhost:5432/db"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert config.load_user_config() == {
        "database_url": "postgresql://u:p@localhost:5432/db"
    }


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
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    assert config.get_models() == []


def test_get_models_env_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没有用户配置时，回退到环境变量中的 DeepSeek 配置。"""
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    monkeypatch.setenv("DEEPSEEK_MODEL", "env-model")

    models = config.get_models()

    assert [model.name for model in models] == ["env-model"]
    assert models[0].api_key == "sk-env"


def test_get_settings_uses_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """用户 JSON 配置应覆盖 Settings 默认值。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "url": "https://example.com/v1",
                "model_name": "my-model",
                "api_key": "sk-test",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    settings = config.get_settings()

    assert settings.deepseek_base_url == "https://example.com/v1"
    assert settings.deepseek_model == "my-model"
    assert settings.deepseek_api_key == "sk-test"


def test_dotenv_only_provides_database_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 只读取 DATABASE_URL，其他键（如 DEEPSEEK_API_KEY）一律忽略。"""
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=sk-dotenv\n"
        "DATABASE_URL=postgresql://u:p@localhost:5432/db\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = config.get_settings()

    assert settings.deepseek_api_key == ""
    assert settings.database_url == "postgresql://u:p@localhost:5432/db"


def test_database_url_env_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DATABASE_URL 优先级：用户 JSON > 环境变量 > .env。"""
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql://dotenv/db\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")
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


def test_get_models_providers_ignore_malformed_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非对象 provider、缺 models、models 非列表、非字符串项、空模型名都跳过。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "providers": [
                    "not-a-provider",
                    {"url": "https://a.example/v1"},
                    {"url": "https://b.example/v1", "models": "solo-model"},
                    {
                        "url": "https://c.example/v1",
                        "models": [123, "", "ok", {"name": "object-entry"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert [model.name for model in config.get_models()] == ["ok"]


def test_get_mcp_servers_reads_camel_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mcpServers 键（标准 MCP 客户端写法）应被解析，非对象的项被忽略。"""
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
                    "broken": "not-an-object",
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


def test_get_mcp_servers_accepts_snake_and_kebab_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mcp_servers / mcp-servers 等别名同样可用。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"mcp_servers": {"a": {"command": "echo"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert config.get_mcp_servers() == {"a": {"command": "echo"}}


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


def test_get_subagents_accepts_snake_and_kebab_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sub_agents / sub-agents 等别名同样可用。"""

    def _write(raw: dict) -> None:
        config_file = tmp_path / "albert-agent-config.json"
        config_file.write_text(json.dumps(raw), encoding="utf-8")
        monkeypatch.setattr(config, "user_config_path", lambda: config_file)
        config.get_subagents.cache_clear()

    _write({"sub_agents": [{"name": "snake", "prompt": "s"}]})
    assert config.get_subagents()[0].name == "snake"

    _write({"sub-agents": [{"name": "kebab", "prompt": "k"}]})
    assert config.get_subagents()[0].name == "kebab"


def test_read_subagents_ignores_malformed_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非列表、非对象、缺字段、空名称/提示词、同名项都跳过。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "subagents": [
                    "not-an-object",
                    {"name": ""},
                    {"name": "no-prompt"},
                    {"name": "empty-prompt", "prompt": "   "},
                    {"name": 123, "prompt": "bad-name"},
                    {"name": "ok", "prompt": "  do it  "},
                    {"name": "ok", "prompt": "duplicate"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert config.read_subagents() == [
        config.SubagentConfig(name="ok", prompt="do it")
    ]


def test_read_subagents_non_list_returns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """subagents 不是数组时按未配置处理（仍会回退到内置默认）。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"subagents": {"name": "x", "prompt": "y"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert config.read_subagents() == []
    assert [subagent.name for subagent in config.get_subagents()] == ["general"]


def test_get_web_fetch_allowed_domains_normalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """白名单应转小写、去前导点、去重，非字符串项忽略。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps(
            {
                "webFetchAllowedDomains": [
                    "Example.com",
                    ".docs.python.org",
                    "example.com",
                    "",
                    123,
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


def test_get_web_fetch_allowed_domains_snake_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """兼容 web_fetch_allowed_domains 写法。"""
    config_file = tmp_path / "albert-agent-config.json"
    config_file.write_text(
        json.dumps({"web_fetch_allowed_domains": ["a.com"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "user_config_path", lambda: config_file)

    assert config.get_web_fetch_allowed_domains() == ("a.com",)


def test_get_web_fetch_allowed_domains_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """未配置白名单时返回空元组（调用方按全部拒绝处理）。"""
    monkeypatch.setattr(config, "user_config_path", lambda: tmp_path / "missing.json")

    assert config.get_web_fetch_allowed_domains() == ()
