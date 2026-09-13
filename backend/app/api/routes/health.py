"""健康检查路由。"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """返回服务存活状态，供探活 / 前端启动检查使用。"""
    return {"status": "ok"}
