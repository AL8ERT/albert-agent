"""事件循环工厂。

psycopg 的异步连接无法在 Windows 的 ProactorEventLoop 上工作，而 uvicorn 默认
在非 reload 模式使用 ProactorEventLoop。通过 `--loop app.core.loop:selector_loop_factory`
让 uvicorn 显式使用 SelectorEventLoop（Linux/macOS 默认即为 Selector，不受影响）。
"""

import asyncio


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """返回 uvicorn 可用的 Selector 事件循环实例。"""
    return asyncio.SelectorEventLoop()
