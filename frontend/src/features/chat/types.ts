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

/** assistant 消息里的思维链片段（思考型模型的 reasoning_content 增量归组）。 */
export type ReasoningPart = {
  kind: 'reasoning'
  id: string
  /** LLM 消息 ID（后端 reasoning 事件的 message_id），同一条消息的增量归组到一块 */
  messageId: string | null
  content: string
}

/** assistant 消息的中间过程块（文本与工具调用按时间顺序排列）。 */
export type ChatPart = TextPart | ToolPart | ReasoningPart

/** 页面上渲染的一条消息（与后端 checkpointer 的消息结构解耦）。 */
export type ChatMessage = {
  id: string
  role: ChatRole
  content: string
  /** 仅 assistant：LLM 中间过程（文本 / 工具调用），按发生顺序渲染 */
  parts?: ChatPart[]
  /** 仅 assistant：本轮 token 用量（流结束时的 done 事件回填） */
  usage?: TokenUsage | null
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
  tool_calls?: { id?: string | null; name?: string; args?: unknown }[]
  /** tool 消息的执行状态：success / error（历史会话回填工具卡片时使用） */
  status?: string | null
  /** 框架注入消息（如 skill 增删差分）：对话视图隐藏，仅在「查看消息」面板展示 */
  hidden?: boolean
}

/** 历史会话摘要（GET /api/chat/threads 列表项，与后端 ThreadSummary 一致）。 */
export type ThreadSummary = {
  /** 会话 ID：点击后用它拉取完整消息并切换当前会话 */
  thread_id: string
  /** 展示标题：后端取首条非隐藏用户消息截断生成 */
  title: string
  /** 最新一轮 run 结束时的消息总数 */
  message_count: number
  /** 最新一轮 run 使用的模型名 */
  model: string
  /** 最新一轮 run 的落库时间（ISO 8601），列表按此倒序 */
  updated_at: string
}

/** GET /api/chat/threads/{thread_id} 的响应。 */
export type ThreadMessagesResponse = {
  thread_id: string
  /** 不在 checkpointer 中，由后端从配置单独带出 */
  system_prompt?: string | null
  messages: ThreadMessage[]
  /** 整个会话的累计 token 用量（与 done 事件同口径），切换历史会话时直接展示 */
  total_usage?: TokenUsage
}

/** token 用量统计（后端 done 事件携带，结构与后端 TokenUsage 一致）。 */
export type TokenUsage = {
  /** 输入（prompt）token 数，不含缓存命中部分 */
  input_tokens: number
  /** 输出（completion）token 数 */
  output_tokens: number
  /** provider 上报的总量：输入 + 缓存命中 + 输出 */
  total_tokens: number
  /** 命中 prompt 缓存的 token 数，provider 未上报时为 0 */
  cached_tokens: number
}

/** SSE 流中的事件类型。 */
export type ChatStreamEvent =
  | { type: 'token'; content: string; message_id?: string | null }
  | { type: 'reasoning'; content: string; message_id?: string | null }
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
  | {
      type: 'done'
      /** 本轮合计：主 agent 各次模型调用 + 子 agent 消耗（后端已并入），未上报时缺失 */
      turn_usage?: TokenUsage
      /** 整个会话累计（后端从 checkpointer 汇总，含历史轮次），未上报时缺失 */
      total_usage?: TokenUsage
    }
