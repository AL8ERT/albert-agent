# Albert Agent Backend

基于 FastAPI + LangChain 的 Agent 后端：用 `create_agent` 构建 agent，通过 `astream` 把模型输出以 SSE 流式推送给前端。

## 环境要求

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)（依赖与虚拟环境均由 uv 管理）

## 应用配置

本机应用配置固定放在用户目录下：`.albert-agent/albert-agent-config.json`（Windows：`C:\Users\<用户名>\.albert-agent\albert-agent-config.json`，Linux/macOS：`~/.albert-agent/albert-agent-config.json`），统一存放模型、MCP servers、子 agent、web_fetch 域名白名单等。

模型按 `providers` 分组：每个 provider 一个 `url` / `api_key`，下面挂自己的 `models`（列表顺序即 `/api/models` 顺序，第一个是默认模型）：

```json
{
  "providers": [
    {
      "url": "https://api.deepseek.com",
      "api_key": "sk-deepseek",
      "models": ["deepseek-flash", "deepseek-reasoner"]
    },
    {
      "url": "https://api.openai.com/v1",
      "api_key": "sk-openai",
      "models": ["gpt-4o"]
    }
  ],
  "mcpServers": {},
  "subagents": [
    {
      "name": "researcher",
      "prompt": "You are a research subagent. Search the web, verify facts and return a cited summary."
    }
  ],
  "webFetchAllowedDomains": []
}
```

- provider 的键名：`url`、`api_key`、`models`（字符串列表）
- 模型列表只从 `providers` 解析：每个 provider 必须提供自己的 `url` / `api_key`，模型名全局去重，重复时保留先出现的 provider
- 未配置 `providers` 时 `/api/models` 返回空列表，对话接口返回 503
- 配置结构由 `app/core/config.py` 的 `UserConfig` 模型定义（字段即文档）：字段类型错误或空值会让读取直接抛 `RuntimeError` 并附校验详情（不做静默跳过），未知顶层键忽略，重复项（模型名 / 子 agent 名 / 域名）去重保留先出现的
- 用户 JSON 只提供 `providers` / `mcpServers` / `subagents` / `webFetchAllowedDomains` 四个顶层键；Settings（如 `AGENT_SYSTEM_PROMPT`、`LLM_TEMPERATURE`、`DATABASE_URL`）从环境变量或 `.env` 读取（见下文）

其他配置项定义在 `app/core/config.py`（如 `AGENT_SYSTEM_PROMPT`、`LLM_TEMPERATURE`），通过环境变量或工作目录下的 `.env` 设置（不属于应用配置）。

### 内置工具

agent 默认挂载以下工具：

| 工具 | 说明 |
| --- | --- |
| `get_current_time` | 获取当前日期时间，可选 IANA 时区（如 `Asia/Shanghai`） |
| `web_search` | DuckDuckGo 网页搜索（`ddgs`，无需 API Key），返回标题/链接/摘要 |
| `read_file` | 读取文本文件（支持 `~` 展开、offset/limit 分页，拒绝二进制与超大文件），用于加载 SKILL.md 正文 |
| `web_fetch` | 抓取白名单域名的 https 页面，HTML 转 Markdown（链接转绝对地址），可顺着返回的链接继续抓取 |
| `use_subagent` | 调用子 agent（传入 agent 名与消息），只把最终答案返回主 agent（`app/subagents/tool.py`） |

### Guardian 安全策略

`app/security/` 提供参数校验，并由 `GuardianMiddleware` 在工具执行前拦截（被拦截时返回错误 ToolMessage，不执行真实工具）：

**read_file 路径**
- 只允许用户主目录与后端进程工作目录内的路径（符号链接会被解析后再判断，防止绕过）；
- 敏感目录黑名单：`.ssh`、`.aws`、`.gnupg`、`.kube`、`.docker`、`.azure`、`.terraform.d`；
- 敏感文件黑名单：`.env`、`.netrc`、`.npmrc`、`.pypirc`、`.git-credentials`、`*_history`、`id_rsa*`、`*.pem`、`*.key`、`*.p12`、`credentials*`、`albert-agent-config.json`（内含 API Key）等。

**web_fetch 域名白名单**
- 必须在应用配置里设置顶层字符串数组（为空则拒绝一切抓取）：

```json
{
  "providers": [
    {
      "url": "https://api.deepseek.com",
      "api_key": "sk-xxxxxxxx",
      "models": ["deepseek-flash"]
    }
  ],
  "webFetchAllowedDomains": ["docs.python.org", "github.com", "raw.githubusercontent.com"]
}
```

- 只允许 `https`、443 端口，不允许 IP 字面量、localhost、URL 内嵌用户名密码；
- 域名支持子域匹配（配置 `example.com` 放行 `docs.example.com`）；
- 重定向逐跳校验，跳到白名单外立即拦截；
- 页面大小上限 1MB，正文按 `max_chars` 截断（默认 20000）。

### MCP Servers

在同一个应用配置里用 `mcpServers` 配置 MCP server。格式遵循 MCP 客户端通用约定：

```json
{
  "providers": [
    {
      "url": "https://api.deepseek.com",
      "api_key": "sk-xxxxxxxx",
      "models": ["deepseek-flash"]
    }
  ],
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"],
      "env": { "SOME_TOKEN": "xxx" }
    },
    "remote": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer xxx" }
    }
  }
}
```

- stdio server 用 `command` / `args` / `env` / `cwd`；远程 server 用 `url` / `headers`，`type` 支持 `http`（默认，streamable HTTP）与 `sse`。
- 可选 `"enabled": false` 单独禁用某个 server。
- 后端启动时加载所有 MCP 工具并缓存，**修改 MCP 配置后需重启后端**；单个 server 连接失败只跳过它并记录日志，不影响其他 server 与内置工具。
- 工具名带 server 前缀（如 `playwright_browser_navigate`），避免多 server 重名。

### 技能（Skills）

技能目录固定放在 `~/.albert-agent/skills/<技能名>/SKILL.md`，用 YAML front matter 描述元数据：

```markdown
---
name: pdf
description: Process and extract text from PDF files
---

技能正文（具体指令、示例、可用脚本说明等）。
```

注入时机（由 `app/skills/middleware.py` 实现）：

- **首轮对话**：技能元数据（名称、描述、SKILL.md 路径）以 `<available_skills>` 隐藏 HumanMessage 追加到消息尾部并持久化，系统提示词保持完全静态；
- **后续轮次**：每次模型调用前对比技能目录，若有新增/删除，把新增技能的元数据和被删除的技能名合并成一条 `<skill_update>` 隐藏 HumanMessage 追加到消息尾部；
- 隐藏消息带 `hide_from_chat` 标记：正常对话视图不显示，在「查看消息」面板中仍可看到（`ThreadMessage.hidden`）。

### 子 Agent（Subagents）

在同一个应用配置里用 `subagents` 配置子 agent，每项两个字段：`name`（调用名）与 `prompt`（子 agent 的系统提示词）。`name` 与 `prompt` 都必须是非空字符串（读取时去首尾空白，空值直接报错），同名项只保留第一条：

```json
{
  "providers": [
    {
      "url": "https://api.deepseek.com",
      "api_key": "sk-xxxxxxxx",
      "models": ["deepseek-flash"]
    }
  ],
  "subagents": [
    {
      "name": "researcher",
      "prompt": "You are a research subagent. Search the web, verify facts and return a cited summary."
    }
  ]
}
```

- 系统内置 `general` 通用任务子 agent，始终可用；用户配置同名子 agent 时以用户配置为准；
- 主 agent 的系统提示词要求先评估任务量：简单任务自己处理，重大任务（多步调研、长文写作、深度分析、多个独立子任务等）拆分成子任务，委派给最合适的子 agent 执行后再汇总答案；
- 注入时机与技能一致（`app/subagents/middleware.py`）：首轮把完整名单渲染成 `<available_subagents>` 隐藏 HumanMessage，后续配置变化以 `<subagent_update>` 差分追加；
- 主 agent 通过 `use_subagent` 工具调用子 agent，传入 agent 名与完整任务消息（子 agent 看不到主对话，消息需自带全部上下文）；
- 子 agent 拥有全部内置 / MCP 工具与技能，在自己的上下文里执行；只有最终答案作为工具结果返回主 agent，中间工具调用不会进入主 agent 上下文；子 agent 不能再调用子 agent（避免递归）；
- 子 agent 名单在进程内缓存，**修改配置后需重启后端**（与 MCP 一致）。

### PostgreSQL（可选）

配置 `DATABASE_URL` 后，checkpointer 从内存切换为 PostgreSQL 持久化（库需已存在，启动时自动建表）：

```
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
```

`DATABASE_URL` 可放在环境变量，或工作目录下的 `.env`（模板见 `.env.example`）。`.env` 由 pydantic-settings 读取，可放置全部 Settings 字段（`APP_NAME`、`CORS_ORIGINS`、`LLM_TEMPERATURE` 等）；优先级：环境变量 > `.env` > 默认值。

启动时会自动创建 LangGraph 的 checkpointer 表，以及记录每次 run 完整 checkpoint 的 `agent_run_checkpoints` 表：

| 列 | 说明 |
| --- | --- |
| `thread_id` | 会话 ID |
| `checkpoint_id` | 本次 run 结束时的 LangGraph checkpoint ID |
| `model` | 使用的模型 |
| `system_prompt` | 本次 run 使用的系统提示词 |
| `message_count` / `messages` | 完整消息列表（JSONB） |
| `created_at` | 记录时间 |

未配置 `DATABASE_URL` 时回退 `InMemorySaver`，且不记录 run 历史。

## 启动

```powershell
uv sync                                  # 安装依赖（首次或依赖变更后）
uv run python -m app --reload            # 开发模式，默认 http://127.0.0.1:8000
uv run python -m app                     # 无 reload 启动
```

Windows 上不要直接使用 `uvicorn app.main:app`：psycopg 异步连接无法运行在 ProactorEventLoop 上，`python -m app` 会显式使用 SelectorEventLoop（Linux/macOS 不受影响）。

启动后可访问 http://127.0.0.1:8000/docs 查看接口文档。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/models` | 返回已配置的模型名列表 |
| POST | `/api/chat/stream` | 发送消息，返回 SSE 流 |
| GET | `/api/chat/threads/{thread_id}` | 查看该线程在 checkpointer 中的消息列表（可选 `?model=`） |

`GET /api/models` 响应：

```json
{ "models": ["deepseek-flash", "deepseek-v4-pro"] }
```

`POST /api/chat/stream` 请求体（`model` 可选，缺省使用列表第一个模型；未知模型返回 400，未配置模型返回 503）：

```json
{ "message": "你好", "model": "deepseek-flash", "thread_id": "default" }
```

响应为 `text/event-stream`，LLM 的中间过程也会推送（前端据此展示文本与工具卡片）：

```
data: {"type":"token","content":"我先搜索一下。","message_id":"..."}

data: {"type":"tool_call","tool_call_id":"call-1","name":"web_search","args":{"query":"albert"},"message_id":"..."}

data: {"type":"tool_result","tool_call_id":"call-1","name":"web_search","content":"...","status":"success"}

data: {"type":"token","content":"根据搜索结果…","message_id":"..."}

data: {"type":"done"}
```

事件类型：

| 事件 | 说明 |
| --- | --- |
| `token` | LLM 增量文本（含工具调用前的中间文本）；`message_id` 标识所属 LLM 消息，前端据此把同一消息的 token 归组到一段 |
| `tool_call` | LLM 请求调用工具：`tool_call_id` / `name` / `args` |
| `tool_result` | 工具执行结果：`tool_call_id` 关联调用，`content` 为结果文本，`status` 为 `success` / `error`（Guardian 拦截也是 error） |
| `error` | 执行异常信息（流内错误） |
| `done` | 流结束 |

## 测试

```powershell
uv run pytest
```

## 目录结构

```
app/
├─ main.py                  # create_app() 入口（lifespan 初始化数据库与 MCP 工具）
├─ core/config.py           # pydantic-settings 配置 + 用户 JSON（模型 / MCP / 子 agent / 域名白名单）
├─ core/messages.py         # 消息 content 文本提取（SSE 与子 agent 工具共用）
├─ agents/assistant.py      # create_agent 工厂（内置工具 + MCP 工具 + use_subagent + 中间件）
├─ agents/prompts.py        # 主 agent / 子 agent 系统提示词（静态框架说明）
├─ tools/builtins.py        # 内置工具：当前时间 / 网页搜索 / 文件读取
├─ tools/web_fetch.py       # web_fetch：白名单域名抓取 + HTML 转 Markdown
├─ security/guard.py        # read_file 路径与 web_fetch URL 校验规则
├─ security/middleware.py   # GuardianMiddleware：工具执行前拦截
├─ mcp/manager.py           # MCP server 加载与进程内缓存
├─ skills/loader.py         # ~/.albert-agent/skills 元数据加载
├─ skills/middleware.py     # 首轮全量 + 后续增删差分的隐藏消息
├─ subagents/loader.py      # 应用配置里的子 agent 加载与渲染
├─ subagents/middleware.py  # 子 agent 名单隐藏消息注入
├─ subagents/tool.py        # use_subagent：调用子 agent，只返回最终答案
├─ api/router.py            # /api 总路由
├─ api/routes/              # health / chat 路由
├─ schemas/chat.py          # 请求与事件模型
└─ services/chat_service.py # astream -> SSE
tests/                      # pytest 测试
```

新增能力时按 `schemas -> services -> api/routes` 分层添加，并在 `api/router.py` 注册路由。
