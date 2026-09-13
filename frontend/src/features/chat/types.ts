/**
 * 聊天功能的共享类型定义。
 */

/** 前端展示用的消息角色。 */
export type ChatRole = 'user' | 'assistant'

/** assistant 消息里的文本片段（对应一次 LLM 输出的文本）。 */
export type TextPart = {
  kind: 'text'
  /** 本地唯一 ID，用作 React key */
  id: string
  /** LLM 消息 ID（后端 token 事件的 message_id），同一条消息的 token 归组到一段 */
  messageId: string | null
  content: string
}

/** assistant 消息里的工具调用片段。 */
export type ToolPart = {
  kind: 'tool'
  id: string
  /** 后端工具调用 ID，用于关联 tool_result */
  callId: string
  name: string
  args: unknown
  /** null 表示工具还在执行中 */
  result: string | null
  /** success / error，执行完成前的 null */
  status: string | null
}

/** assistant 消息的中间过程块（文本与工具调用按时间顺序排列）。 */
export type ChatPart = TextPart | ToolPart

/** 页面上渲染的一条消息（与后端 checkpointer 的消息结构解耦）。 */
export type ChatMessage = {
  id: string
  role: ChatRole
  content: string
  /** 仅 assistant：LLM 中间过程（文本 / 工具调用），按发生顺序渲染 */
  parts?: ChatPart[]
}

/** GET /api/models 的响应。 */
export type ModelListResponse = {
  models: string[]
}

/** 后端序列化后的单条消息（来自 checkpointer）。 */
export type ThreadMessage = {
  type: string // human / ai / system / tool
  content: string
  id?: string | null
  name?: string | null
  tool_call_id?: string | null
  tool_calls?: { name?: string; args?: unknown }[]
  /** 框架注入消息（如 skill 增删差分）：对话视图隐藏，仅在「查看消息」面板展示 */
  hidden?: boolean
}

/** GET /api/chat/threads/{thread_id} 的响应。 */
export type ThreadMessagesResponse = {
  thread_id: string
  /** 不在 checkpointer 中，由后端从配置单独带出 */
  system_prompt?: string | null
  messages: ThreadMessage[]
}

/** SSE 流中的事件类型。 */
export type ChatStreamEvent =
  | { type: 'token'; content: string; message_id?: string | null }
  | {
      type: 'tool_call'
      tool_call_id?: string | null
      name?: string | null
      args?: unknown
      message_id?: string | null
    }
  | {
      type: 'tool_result'
      tool_call_id?: string | null
      name?: string | null
      content?: string | null
      status?: string | null
    }
  | { type: 'error'; message: string }
  | { type: 'done' }
