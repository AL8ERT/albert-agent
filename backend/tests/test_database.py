"""数据库模块测试：未配置 PostgreSQL 时的内存兜底行为。"""

import asyncio

from langgraph.checkpoint.memory import InMemorySaver

from app.core import database


def test_get_checkpointer_falls_back_to_memory() -> None:
    """未初始化连接池时，get_checkpointer 返回同一个内存实例。"""
    checkpointer = database.get_checkpointer()

    assert isinstance(checkpointer, InMemorySaver)
    assert database.get_checkpointer() is checkpointer


def test_save_run_checkpoint_without_pool_is_noop() -> None:
    """没有连接池时写入审计表应静默跳过，不抛异常。"""
    asyncio.run(
        database.save_run_checkpoint(
            thread_id="thread-1",
            checkpoint_id="checkpoint-1",
            model="test-model",
            system_prompt="prompt",
            messages=[],
        )
    )
