"""FastAPI 应用装配：lifespan、CORS 与路由注册。

lifespan 在进程启动时初始化 PostgreSQL checkpointer（含建表）并加载 MCP 工具，
退出时释放连接池。
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import close_database, init_database
from app.mcp.manager import refresh_mcp_tools

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动时连数据库、加载 MCP 工具，关闭时释放连接。"""
    await init_database(get_settings().database_url)
    try:
        tools = await refresh_mcp_tools()
        logger.info("MCP tools ready: %d tool(s)", len(tools))
    except Exception:
        # MCP 不可用不应阻止应用启动：内置工具与其余功能仍然可用
        logger.exception("MCP tool initialization failed; continuing without MCP tools")
    yield
    await close_database()


def create_app() -> FastAPI:
    """创建并配置 FastAPI 实例（测试中也会复用该工厂）。"""
    settings = get_settings()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    # 前端开发服务器与后端不同源，放开 CORS；生产环境可通过 CORS_ORIGINS 收紧
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)
    return app


# uvicorn / gunicorn 的 ASGI 入口
app = create_app()
