"""API 层测试：健康检查、模型列表、聊天流、历史会话列表与线程消息接口。

通过 monkeypatch 替换路由模块里的依赖（get_models / get_thread_messages /
list_threads），避免测试真正调用模型或访问数据库。
"""

from datetime import datetime

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.agents.assistant import build_system_prompt
from app.api.routes import chat as chat_route
from app.api.routes import models as models_route
from app.core.config import ModelConfig
from app.main import app
from app.schemas.chat import ThreadMessage, ThreadSummary, TokenUsage

# TestClient 不会触发 lifespan，因此测试环境不会连接 PostgreSQL
client = TestClient(app)


def test_health() -> None:
    """健康检查返回固定状态。"""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_stream_requires_message() -> None:
    """空 message 违反 min_length=1，应返回 422。"""
    response = client.post("/api/chat/stream", json={"message": ""})
    assert response.status_code == 422


def test_list_models(monkeypatch: MonkeyPatch) -> None:
    """模型列表接口按配置顺序返回模型名。"""
    monkeypatch.setattr(
        models_route,
        "get_models",
        lambda: [
            ModelConfig(name="deepseek-chat", base_url="https://a", api_key="sk-a"),
            ModelConfig(name="deepseek-reasoner", base_url="https://b", api_key="sk-b"),
        ],
    )

    response = client.get("/api/models")

    assert response.status_code == 200
    assert response.json() == {"models": ["deepseek-chat", "deepseek-reasoner"]}


def test_chat_stream_without_models(monkeypatch: MonkeyPatch) -> None:
    """没有任何模型配置时返回 503。"""
    monkeypatch.setattr(chat_route, "get_models", lambda: [])

    response = client.post("/api/chat/stream", json={"message": "hi"})

    assert response.status_code == 503


def test_chat_stream_rejects_unknown_model(monkeypatch: MonkeyPatch) -> None:
    """请求了未配置的模型名时返回 400。"""
    monkeypatch.setattr(
        chat_route,
        "get_models",
        lambda: [ModelConfig(name="known", base_url="https://a", api_key="sk-a")],
    )

    response = client.post("/api/chat/stream", json={"message": "hi", "model": "unknown"})

    assert response.status_code == 400


def test_get_thread_returns_checkpointer_messages(monkeypatch: MonkeyPatch) -> None:
    """线程消息接口返回 messages / system_prompt / total_usage 三件套。"""
    monkeypatch.setattr(
        chat_route,
        "get_models",
        lambda: [ModelConfig(name="known", base_url="https://a", api_key="sk-a")],
    )

    # 用假实现替换服务层，专注验证路由的组装与响应结构
    async def fake_get_thread_messages(
        model_name: str, thread_id: str
    ) -> tuple[list[ThreadMessage], TokenUsage | None]:
        return (
            [
                ThreadMessage(type="human", content="hi"),
                ThreadMessage(type="ai", content="hello"),
            ],
            TokenUsage(input_tokens=10, output_tokens=2, total_tokens=12),
        )

    monkeypatch.setattr(chat_route, "get_thread_messages", fake_get_thread_messages)

    response = client.get("/api/chat/threads/thread-1")

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "thread-1"
    # system_prompt 应来自当前配置（而非 checkpointer）
    assert body["system_prompt"] == build_system_prompt()
    assert [(item["type"], item["content"]) for item in body["messages"]] == [
        ("human", "hi"),
        ("ai", "hello"),
    ]
    # 累计用量原样透传，前端切换历史会话时直接展示
    assert body["total_usage"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "cached_tokens": 0,
    }


def test_list_threads_endpoint(monkeypatch: MonkeyPatch) -> None:
    """历史会话列表接口返回服务层组装的摘要数组。"""

    async def fake_list_threads(limit: int = 50) -> list[ThreadSummary]:
        return [
            ThreadSummary(
                thread_id="thread-1",
                title="你好",
                message_count=2,
                model="known",
                updated_at=datetime(2026, 9, 20, 12, 0, 0),
            )
        ]

    monkeypatch.setattr(chat_route, "list_threads", fake_list_threads)

    response = client.get("/api/chat/threads")

    assert response.status_code == 200
    body = response.json()
    assert len(body["threads"]) == 1
    assert body["threads"][0]["thread_id"] == "thread-1"
    assert body["threads"][0]["title"] == "你好"
    # datetime 序列化为 ISO 8601
    assert body["threads"][0]["updated_at"].startswith("2026-09-20T12:00:00")


def test_list_threads_endpoint_empty_without_database(
    monkeypatch: MonkeyPatch,
) -> None:
    """未配置数据库时列表接口正常返回空数组（历史是附加能力，不报错）。"""

    async def fake_list_threads(limit: int = 50) -> list[ThreadSummary]:
        return []

    monkeypatch.setattr(chat_route, "list_threads", fake_list_threads)

    response = client.get("/api/chat/threads")

    assert response.status_code == 200
    assert response.json() == {"threads": []}


def test_get_thread_rejects_unknown_model(monkeypatch: MonkeyPatch) -> None:
    """线程消息接口同样校验模型名（query 参数）。"""
    monkeypatch.setattr(
        chat_route,
        "get_models",
        lambda: [ModelConfig(name="known", base_url="https://a", api_key="sk-a")],
    )

    response = client.get("/api/chat/threads/thread-1", params={"model": "unknown"})

    assert response.status_code == 400
