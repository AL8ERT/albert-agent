"""PostgreSQL 持久化层：LangGraph checkpointer + 每次 run 的审计表。

- checkpointer：配置 DATABASE_URL 后使用 AsyncPostgresSaver（会话状态跨进程/重启保留）；
  未配置时回退到进程内 InMemorySaver，保证本地开发与测试可无依赖运行。
- agent_run_checkpoints：LangGraph 自带的 checkpoints 表是给框架读写的二进制/blob 结构，
  这里额外落一张可读的扁平表，记录每次 run 结束时的完整消息快照，便于调试与审计。

注意：psycopg 的异步连接在 Windows 上不能运行于 ProactorEventLoop，因此启动入口
（app/__main__.py）强制使用 SelectorEventLoop；init_database 里也会做一次防御性检查。
"""

import asyncio
import logging
import sys
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

# 审计表名：每次 run 一条记录
RUN_CHECKPOINTS_TABLE = "agent_run_checkpoints"

# 审计表结构：
# - (thread_id, checkpoint_id) 唯一，重复写入同一 checkpoint 时直接忽略（幂等）
# - messages 以 JSONB 存储，便于用 SQL 直接查询完整消息列表
_CREATE_RUN_CHECKPOINTS = f"""
CREATE TABLE IF NOT EXISTS {RUN_CHECKPOINTS_TABLE} (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL,
    checkpoint_id TEXT NOT NULL,
    model TEXT NOT NULL,
    system_prompt TEXT,
    message_count INTEGER NOT NULL,
    messages JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (thread_id, checkpoint_id)
)
"""

# 写入审计表；ON CONFLICT 保证同一 checkpoint 重复保存不会报错或产生重复行
_INSERT_RUN_CHECKPOINT = f"""
INSERT INTO {RUN_CHECKPOINTS_TABLE}
    (thread_id, checkpoint_id, model, system_prompt, message_count, messages)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (thread_id, checkpoint_id) DO NOTHING
"""

# 历史会话列表：每个 thread 只取最新一条 run（DISTINCT ON + 内层按时间取最新），
# 外层再按时间倒序排会话。messages 一并带出，供服务层提取会话标题（首条用户消息）。
_LIST_THREAD_RUNS = f"""
SELECT thread_id, model, message_count, messages, created_at
FROM (
    SELECT DISTINCT ON (thread_id)
        thread_id, model, message_count, messages, created_at
    FROM {RUN_CHECKPOINTS_TABLE}
    ORDER BY thread_id, created_at DESC
) AS latest_per_thread
ORDER BY created_at DESC
LIMIT %s
"""

# 模块级单例：由 FastAPI lifespan 在启动/关闭时初始化和释放
_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None
# 未配置数据库时的兜底实现（进程内存储，重启即丢）
_fallback_checkpointer: InMemorySaver | None = None


async def init_database(database_url: str) -> None:
    """初始化连接池与 checkpointer；未配置 database_url 时保持内存模式。

    启动时会自动执行：
    1. LangGraph checkpointer 建表（checkpoints / checkpoint_blobs / checkpoint_writes 等）；
    2. 本模块审计表 agent_run_checkpoints 的建表。
    """
    global _pool, _checkpointer
    if not database_url:
        logger.warning(
            "DATABASE_URL is not set; using in-memory checkpointer and "
            "disabling run checkpoint history."
        )
        return

    # psycopg 的异步实现只支持 SelectorEventLoop；Proactor 下连接会直接失败，
    # 这里提前给出清晰报错，而不是让连接池反复超时。
    if sys.platform == "win32" and not isinstance(
        asyncio.get_running_loop(), asyncio.SelectorEventLoop
    ):
        raise RuntimeError(
            "The async PostgreSQL checkpointer requires a SelectorEventLoop on "
            "Windows. Start the server with `uv run python -m app` instead of "
            "the plain uvicorn CLI."
        )

    # autocommit + prepare_threshold=0 是 LangGraph 对 psycopg 连接池的推荐配置
    pool = AsyncConnectionPool(
        conninfo=database_url,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open(wait=True, timeout=15)

    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()  # 创建/迁移 LangGraph 自身的表
    async with pool.connection() as conn:
        await conn.execute(_CREATE_RUN_CHECKPOINTS)  # 创建审计表

    # 全部成功后再赋值给模块级变量，避免半初始化状态被其他请求读到
    _pool = pool
    _checkpointer = checkpointer
    logger.info("PostgreSQL checkpointer ready (table %s).", RUN_CHECKPOINTS_TABLE)


async def close_database() -> None:
    """关闭连接池并清空单例（由 lifespan 在应用退出时调用）。"""
    global _pool, _checkpointer
    if _pool is not None:
        await _pool.close()
    _pool = None
    _checkpointer = None


def get_checkpointer() -> BaseCheckpointSaver:
    """返回全局 checkpointer：优先 PostgreSQL，其次内存实现。

    注意内存实现按进程隔离，多 worker / 重启后历史会丢失。
    """
    global _fallback_checkpointer
    if _checkpointer is not None:
        return _checkpointer
    if _fallback_checkpointer is None:
        _fallback_checkpointer = InMemorySaver()
    return _fallback_checkpointer


# 每个会话最新一条 run 的原始数据（历史会话列表的数据源）
ThreadRunRow = tuple[str, str, int, list[dict[str, Any]], Any]


async def list_thread_runs(limit: int = 50) -> list[ThreadRunRow]:
    """读取历史会话列表：每个 thread 取最新一条 run，按时间倒序。

    返回原始行 (thread_id, model, message_count, messages, created_at)，
    标题提取等展示逻辑由服务层负责。未配置数据库时返回空列表
    （内存模式没有审计表，自然也没有历史）。
    """
    if _pool is None:
        return []
    try:
        async with _pool.connection() as conn:
            cursor = await conn.execute(_LIST_THREAD_RUNS, (limit,))
            rows = await cursor.fetchall()
            return [
                (row[0], row[1], row[2], row[3], row[4]) for row in rows
            ]
    except Exception:
        # 列表属于附加能力：读失败只记日志，向上返回空列表而不是让接口报错
        logger.exception("Failed to list thread runs")
        return []


async def save_run_checkpoint(
    *,
    thread_id: str,
    checkpoint_id: str,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> None:
    """把一次 run 的完整 checkpoint 快照写入审计表。

    - 未配置数据库时静默跳过（本地内存模式没有审计表）；
    - 写失败只记日志，不影响已经完成的对话（可观测性属于附加能力）。
    """
    if _pool is None:
        return
    try:
        async with _pool.connection() as conn:
            await conn.execute(
                _INSERT_RUN_CHECKPOINT,
                (
                    thread_id,
                    checkpoint_id,
                    model,
                    system_prompt,
                    len(messages),
                    Jsonb(messages),
                ),
            )
    except Exception:
        logger.exception("Failed to save run checkpoint for thread %s", thread_id)
