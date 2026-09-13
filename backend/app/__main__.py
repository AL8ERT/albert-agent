"""启动入口：`uv run python -m app [--reload] [--host H] [--port P]`。

不要直接使用 `uvicorn app.main:app`：uvicorn 在 import 应用之前就创建了事件循环，
非 reload 模式下 Windows 会使用 ProactorEventLoop，导致 psycopg 异步连接失败。
这里显式指定 Selector 事件循环工厂，保证任何模式下都能正常连接 PostgreSQL。
"""

import argparse

import uvicorn


def main() -> None:
    """解析命令行参数并以正确的 loop 配置启动 uvicorn。"""
    parser = argparse.ArgumentParser(description="Run the Albert Agent API server.")
    parser.add_argument("--host", default="127.0.0.1")  # 默认仅本机访问
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")  # 开发模式热重载
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        # 自定义 loop 工厂必须写成 "模块:属性" 字符串，uvicorn 会 import 后直接使用
        loop="app.core.loop:selector_loop_factory",
    )


if __name__ == "__main__":
    main()
