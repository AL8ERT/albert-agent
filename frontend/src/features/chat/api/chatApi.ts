/**
 * 聊天 API：模型列表、线程消息、SSE 流式对话。
 */

import { getJson, postJson } from '@/shared/lib/http'
import { parseSseStream } from '@/shared/lib/sse'
import type {
  ChatStreamEvent,
  ModelListResponse,
  ThreadMessagesResponse,
  ThreadSummary,
  TokenUsage,
} from '../types'

/** 获取后端已配置的模型名列表。 */
export async function fetchModels(signal?: AbortSignal): Promise<string[]> {
  const data = await getJson<ModelListResponse>('/api/models', signal)
  return data.models
}

/** 历史会话列表：每个会话一条摘要，按最近活跃时间倒序（无数据库时为空数组）。 */
export async function fetchThreadSummaries(
  signal?: AbortSignal,
): Promise<ThreadSummary[]> {
  const data = await getJson<{ threads: ThreadSummary[] }>(
    '/api/chat/threads',
    signal,
  )
  return data.threads
}

/** 读取指定线程在 checkpointer 中的消息（用于「查看消息」面板）。 */
export async function fetchThreadMessages(
  threadId: string,
  model?: string,
  signal?: AbortSignal,
): Promise<ThreadMessagesResponse> {
  // model 可选：缺省时后端使用模型列表第一个；路径与查询参数都需要 URL 编码
  const query = model ? `?model=${encodeURIComponent(model)}` : ''
  return getJson<ThreadMessagesResponse>(
    `/api/chat/threads/${encodeURIComponent(threadId)}${query}`,
    signal,
  )
}

/** 工具调用事件（LLM 请求执行工具）。 */
export type ToolCallEvent = {
  toolCallId: string | null
  name: string | null
  args: unknown
}

/** 工具结果事件（工具执行完成，关联到 tool_call）。 */
export type ToolResultEvent = {
  toolCallId: string | null
  name: string | null
  content: string
  status: string | null
}

export type StreamChatOptions = {
  model?: string
  /** 会话 ID：相同 ID 会复用后端 checkpointer 中的历史，实现多轮对话 */
  threadId?: string
  /** 增量文本；messageId 标识所属 LLM 消息（可能为 null） */
  onToken: (token: string, messageId: string | null) => void
  /** 思维链增量（思考型模型才有）；归组语义与 onToken 一致 */
  onReasoning?: (token: string, messageId: string | null) => void
  /** LLM 发起工具调用 */
  onToolCall?: (call: ToolCallEvent) => void
  /** 工具执行结果 */
  onToolResult?: (result: ToolResultEvent) => void
  signal?: AbortSignal
}

/** streamChat 的返回值：done 事件携带的用量统计（provider 未上报时为 undefined）。 */
export type StreamChatResult = {
  /** 本轮合计（含工具循环的多次模型调用与子 agent 消耗） */
  turnUsage?: TokenUsage
  /** 整个会话累计（后端从 checkpointer 汇总） */
  totalUsage?: TokenUsage
}

/**
 * 发送一条消息并以 SSE 流接收回复。
 * token / tool_call / tool_result 通过对应回调返回；error 事件会抛出异常；
 * done 事件的用量统计（本轮 / 会话累计）作为返回值带出。
 */
export async function streamChat(
  message: string,
  {
    model,
    threadId,
    onToken,
    onReasoning,
    onToolCall,
    onToolResult,
    signal,
  }: StreamChatOptions,
): Promise<StreamChatResult> {
  const response = await postJson(
    '/api/chat/stream',
    { message, model, thread_id: threadId },
    signal,
  )
  if (!response.body) {
    throw new Error('Response body is not readable')
  }

  let result: StreamChatResult = {}
  let sawDone = false
  for await (const data of parseSseStream(response.body)) {
    const event = JSON.parse(data) as ChatStreamEvent
    if (event.type === 'token') {
      onToken(event.content, event.message_id ?? null)
    } else if (event.type === 'reasoning') {
      onReasoning?.(event.content, event.message_id ?? null)
    } else if (event.type === 'tool_call') {
      onToolCall?.({
        toolCallId: event.tool_call_id ?? null,
        name: event.name ?? null,
        args: event.args,
      })
    } else if (event.type === 'tool_result') {
      onToolResult?.({
        toolCallId: event.tool_call_id ?? null,
        name: event.name ?? null,
        content: event.content ?? '',
        status: event.status ?? null,
      })
    } else if (event.type === 'error') {
      // 后端把执行异常也放在 SSE 里，这里统一转换成 Promise 异常
      throw new Error(event.message)
    } else if (event.type === 'done') {
      // done 是最后一个事件：把用量统计存起来，循环结束后随返回值带出
      sawDone = true
      result = {
        turnUsage: event.turn_usage,
        totalUsage: event.total_usage,
      }
    }
  }
  // 后端约定无论如何都以 done 收尾；流被中途掐断（如后端热重载）时
  // 若无此判断，调用方会正常返回，工具卡片永远停在「执行中…」
  if (!sawDone) {
    throw new Error('连接中断：未收到 done 事件（后端可能已重启，请重试）')
  }
  return result
}
