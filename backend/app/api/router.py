"""API 总路由：所有业务路由统一挂到 /api 前缀下。"""

from fastapi import APIRouter

from app.api.routes import chat, health, models

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(models.router)
api_router.include_router(chat.router)
