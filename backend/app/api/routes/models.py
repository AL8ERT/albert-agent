"""模型列表路由。"""

from fastapi import APIRouter

from app.core.config import get_models
from app.schemas.chat import ModelListResponse

router = APIRouter(tags=["models"])


@router.get("/models")
async def list_models() -> ModelListResponse:
    """返回已配置的模型名列表（前端用于模型下拉框）。"""
    return ModelListResponse(models=[model.name for model in get_models()])
