# Albert Agent Frontend

React 19 + TypeScript + Vite 的聊天前端：把消息发给后端，接收 SSE 流并逐字渲染回复。

对话视图会展示 LLM 的完整中间过程：工具调用前的文本逐字渲染，工具调用（名称 + 入参）与执行结果以卡片形式插入，工具执行期间显示「执行中…」，结束后回填结果（Guardian 拦截 / 工具报错标为失败）。每条 assistant 消息由按时间顺序排列的文本段与工具卡片组成。

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
├─ App.tsx                  # 组合层
├─ styles/global.css        # 全局样式变量
├─ shared/lib/              # http / SSE 解析等通用工具
└─ features/chat/
   ├─ api/chatApi.ts        # 调用后端流式接口（token / tool_call / tool_result）、获取模型列表
   ├─ hooks/useChat.ts      # 消息/模型状态管理，把流事件归组为文本段与工具卡片
   ├─ components/           # Header / ModelSelector / MessageList / MessageItem / ToolCallCard / Composer
   └─ types.ts              # 领域类型
```

`@` 别名指向 `src/`。新增功能时在 `src/features/` 下新建同名目录，跨功能复用的代码放 `src/shared/`。
