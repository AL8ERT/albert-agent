"""API 层测试：健康检查、模型列表、聊天流与线程消息接口。

通过 monkeypatch 替换路由模块里的依赖（get_models / get_thread_messages），
避免测试真正调用模型或访问数据库。
"""

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.agents.assistant import build_system_prompt
from app.api.routes import chat as chat_route
from app.api.routes import models as models_route
from app.core.config import ModelConfig
from app.main import app
from app.schemas.chat import ThreadMessage

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
    """线程消息接口返回 messages 以及不在 checkpointer 里的 system_prompt。"""
    monkeypatch.setattr(
        chat_route,
        "get_models",
        lambda: [ModelConfig(name="known", base_url="https://a", api_key="sk-a")],
    )

    # 用假实现替换服务层，专注验证路由的组装与响应结构
    async def fake_get_thread_messages(
        model_name: str, thread_id: str
    ) -> list[ThreadMessage]:
        return [
            ThreadMessage(type="human", content="hi"),
            ThreadMessage(type="ai", content="hello"),
        ]

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


def test_get_thread_rejects_unknown_model(monkeypatch: MonkeyPatch) -> None:
    """线程消息接口同样校验模型名（query 参数）。"""
    monkeypatch.setattr(
        chat_route,
        "get_models",
        lambda: [ModelConfig(name="known", base_url="https://a", api_key="sk-a")],
    )

    response = client.get("/api/chat/threads/thread-1", params={"model": "unknown"})

    assert response.status_code == 400
