"""测试用远程 MCP server（streamable HTTP）：提供「糖果算法」工具。

手动启动（会在 http://127.0.0.1:8765/mcp 提供服务）：
    .venv\\Scripts\\python.exe tests\\mcp_candy_server.py

对应应用配置：
    "mcpServers": {
      "candy": { "type": "http", "url": "http://127.0.0.1:8765/mcp" }
    }
"""

from mcp.server.fastmcp import FastMCP

HOST = "127.0.0.1"
PORT = 8765

mcp = FastMCP("candy", host=HOST, port=PORT)


@mcp.tool()
def algorithm(a: float, b: float, c: float) -> float:
    """糖果算法：返回 a + b * c。"""
    return a + b * c


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
