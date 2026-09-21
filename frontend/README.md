# Albert Agent Frontend

React 19 + TypeScript + Vite 的聊天前端：把消息发给后端，接收 SSE 流并逐字渲染回复。

对话视图会展示 LLM 的完整中间过程：工具调用前的文本逐字渲染，工具调用（名称 + 入参）与执行结果以卡片形式插入，工具执行期间显示「执行中…」，结束后回填结果（Guardian 拦截 / 工具报错标为失败）。每条 assistant 消息由按时间顺序排列的文本段与工具卡片组成。

思维链（思考型模型）：后端把第三方 provider 的 `reasoning_content` 增量以 `reasoning` 事件推送（结构与 `token` 同构），前端归组成可折叠的思考块——流式期间展开实时显示（头部「思考中…」呼吸动画），本轮思考结束后自动折叠成「已深度思考」一行，点击头部随时手动展开 / 收起。仅 GLM-4.5+ / DeepSeek-R1 等思考型模型会出现，普通模型不显示（见后端 README 的事件契约）。

token 用量统计：每轮流结束（SSE `done` 事件）后，assistant 消息底部显示本轮「输入 / 缓存命中 / 输出」，顶部栏显示整个会话的累计用量（「新对话」时重置）；「输入」不含缓存命中，命中段带缓存命中率（命中 / 总输入，如 `缓存命中 1,024 (81.4%)`）；provider 未上报 usage 时不显示。子 agent 消耗已并入总数（见后端 README）。

历史对话：顶部栏「历史」按钮打开左侧会话列表（标题 / 相对时间 / 消息数，当前会话高亮），点击即可切换——消息与工具卡片结果按 `tool_call_id` 重建，会话累计用量一并恢复，之后继续发消息即在该会话上下文中进行。列表来自后端审计表聚合，**未配置 PostgreSQL 时列表为空**（见后端 README）。

## 环境要求

- Node.js 20.19+ / 22.12+（本机使用 v24）
- npm

## 启动

```powershell
npm install     # 首次
npm run dev     # 开发模式，默认 http://localhost:5173
```

启动前请确保后端已在 `http://127.0.0.1:8000` 运行（见 `../backend/README.md`）。

开发服务器通过 Vite 代理把 `/api` 转发到后端（配置在 `vite.config.ts`），因此无需额外处理跨域。

页面顶部会请求 `GET /api/models` 并展示模型下拉框，发送消息时把选中的模型名一起传给后端。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `npm run dev` | 启动开发服务器 |
| `npm run build` | 类型检查 + 生产构建（输出到 `dist/`） |
| `npm run preview` | 本地预览生产构建 |
| `npm run lint` | oxlint 检查 |

## 目录结构

```
src/
├─ App.tsx                  # 组合层（历史侧栏 + 主区 + 消息查看弹层）
├─ styles/global.css        # 全局样式变量
├─ shared/lib/              # http / SSE 解析等通用工具
├─ shared/markdown/         # assistant 消息 Markdown 渲染（GFM + KaTeX 公式 + mermaid 图懒加载）
└─ features/chat/
   ├─ api/chatApi.ts        # 调用后端流式接口（token / reasoning / tool_call / tool_result / done 用量统计）、模型列表、历史会话列表
   ├─ hooks/useChat.ts      # 消息/模型/历史会话状态管理，把流事件归组为思维链块、文本段与工具卡片
   ├─ lib/usage.ts          # token 用量的展示格式化
   ├─ lib/history.ts        # 历史消息重建（ThreadMessage -> ChatMessage）与相对时间格式化
   ├─ components/           # Header / ModelSelector / ThreadSidebar / MessageList / MessageItem / ReasoningBlock / ToolCallCard / Composer
   └─ types.ts              # 领域类型
```

`@` 别名指向 `src/`。新增功能时在 `src/features/` 下新建同名目录，跨功能复用的代码放 `src/shared/`。

### 消息 Markdown 渲染

assistant 文本段统一经 `shared/markdown/MarkdownContent`（react-markdown）渲染：

- **GFM**：表格、任务列表、删除线（remark-gfm）；
- **LaTeX**：`$...$` 行内与 `$$...$$` 块级公式，KaTeX 渲染（remark-math + rehype-katex）；
- **Mermaid**：```` ```mermaid ```` 代码块交给 `MermaidDiagram`，首次遇到图才动态 import mermaid（strict 安全级别）渲染成 SVG，普通对话不付出加载成本；流式期间代码块不完整时先回退展示源码，内容完整后自动重试成图；
- 组件 `memo` 缓存：流式期间只有内容变化的消息重新解析，历史消息不重复走渲染管线；
- 安全：react-markdown 默认不渲染原始 HTML（未启用 rehype-raw），mermaid SVG 为本地生成，无 XSS 注入面。

用户消息保持纯文本展示（主流聊天应用惯例，避免用户输入被意外格式化）。
