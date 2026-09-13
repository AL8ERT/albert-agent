/**
 * useChat：聊天页面的核心状态管理。
 *
 * 负责：
 * - 加载模型列表、维护当前选中的模型；
 * - 维护当前 threadId（会话标识，多轮对话复用同一个 ID）；
 * - 发送消息并把 SSE token 增量写入最后一条 assistant 消息；
 * - 「查看消息」面板的打开/关闭与数据加载（读取后端 checkpointer）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchModels, fetchThreadMessages, streamChat } from '../api/chatApi'
import type { ChatMessage, ChatPart, ThreadMessage } from '../types'

// 前端本地消息自增 ID，仅用于 React 列表 key 与流式更新定位
let nextId = 0

function createMessageId(): string {
  nextId += 1
  return `message-${nextId}`
}

/** 「查看消息」面板的聚合状态。 */
type InspectorState = {
  open: boolean
  isLoading: boolean
  error: string | null
  systemPrompt: string | null
  messages: ThreadMessage[]
}

const INITIAL_INSPECTOR_STATE: InspectorState = {
  open: false,
  isLoading: false,
  error: null,
  systemPrompt: null,
  messages: [],
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  // 每个 hook 实例对应一个会话；新建对话时重置为新的 UUID
  const [threadId, setThreadId] = useState(() => crypto.randomUUID())
  const [models, setModels] = useState<string[]>([])
  const [selectedModel, setSelectedModel] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [inspector, setInspector] = useState(INITIAL_INSPECTOR_STATE)
  const bottomRef = useRef<HTMLDivElement>(null)

  // 初始化：拉取模型列表，默认选中第一个；组件卸载时中断请求
  useEffect(() => {
    const controller = new AbortController()
    fetchModels(controller.signal)
      .then((names) => {
        setModels(names)
        // 保留用户已选模型，仅在为空时回退到第一个
        setSelectedModel((current) => current || names[0] || '')
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
    return () => controller.abort()
  }, [])

  // 消息变化时滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(
    async (text: string) => {
      const content = text.trim()
      // 空消息或正在流式回复时忽略本次发送
      if (!content || isStreaming) return

      const userMessage: ChatMessage = {
        id: createMessageId(),
        role: 'user',
        content,
      }
      // 先插入一条空的 assistant 消息，后续 token / 工具事件会往它上面追加
      const assistantMessage: ChatMessage = {
        id: createMessageId(),
        role: 'assistant',
        content: '',
        parts: [],
      }

      setMessages((prev) => [...prev, userMessage, assistantMessage])
      setError(null)
      setIsStreaming(true)

      /** 把一次变化合并进本次的 assistant 消息（parts 按时间顺序排列）。 */
      const updateParts = (updater: (parts: ChatPart[]) => ChatPart[]) => {
        setMessages((prev) =>
          prev.map((message) =>
            message.id === assistantMessage.id
              ? { ...message, parts: updater(message.parts ?? []) }
              : message,
          ),
        )
      }

      try {
        await streamChat(content, {
          model: selectedModel || undefined,
          threadId,
          // 同一条 LLM 消息的 token 追加到同一段文本；换消息则新开一段
          onToken: (token, messageId) => {
            updateParts((parts) => {
              const last = parts[parts.length - 1]
              if (
                last?.kind === 'text' &&
                (messageId === null || last.messageId === messageId)
              ) {
                return [
                  ...parts.slice(0, -1),
                  { ...last, content: last.content + token },
                ]
              }
              return [
                ...parts,
                {
                  kind: 'text',
                  id: createMessageId(),
                  messageId,
                  content: token,
                },
              ]
            })
          },
          // LLM 请求调用工具：先插入一张「执行中」的工具卡片
          onToolCall: ({ toolCallId, name, args }) => {
            updateParts((parts) => [
              ...parts,
              {
                kind: 'tool',
                id: createMessageId(),
                callId: toolCallId ?? '',
                name: name ?? '',
                args,
                result: null,
                status: null,
              },
            ])
          },
          // 工具执行完成：把结果回填到对应的工具卡片
          onToolResult: ({ toolCallId, content, status }) => {
            updateParts((parts) =>
              parts.map((part) =>
                part.kind === 'tool' && part.callId === (toolCallId ?? '')
                  ? { ...part, result: content, status: status ?? 'success' }
                  : part,
              ),
            )
          },
        })
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
        // 出错时移除空的 assistant 占位消息，并把没等到结果的工具卡片标为失败
        setMessages((prev) =>
          prev
            .filter(
              (message) =>
                message.id !== assistantMessage.id ||
                (message.parts?.length ?? 0) > 0,
            )
            .map((message) =>
              message.id === assistantMessage.id
                ? {
                    ...message,
                    parts: (message.parts ?? []).map((part) =>
                      part.kind === 'tool' && part.result === null
                        ? {
                            ...part,
                            result: '（未收到执行结果）',
                            status: 'error',
                          }
                        : part,
                    ),
                  }
                : message,
            ),
        )
      } finally {
        setIsStreaming(false)
      }
    },
    [isStreaming, selectedModel, threadId],
  )

  /** 开始新对话：换新的 threadId 并清空消息，旧会话历史仍保留在后端。 */
  const startNewChat = useCallback(() => {
    if (isStreaming) return
    setThreadId(crypto.randomUUID())
    setMessages([])
    setError(null)
  }, [isStreaming])

  /** 从后端加载当前线程在 checkpointer 中的消息（面板打开和刷新共用）。 */
  const loadThreadMessages = useCallback(() => {
    setInspector((prev) => ({ ...prev, isLoading: true, error: null }))
    fetchThreadMessages(threadId, selectedModel || undefined)
      .then((data) =>
        setInspector({
          open: true,
          isLoading: false,
          error: null,
          systemPrompt: data.system_prompt ?? null,
          messages: data.messages,
        }),
      )
      .catch((err: unknown) =>
        setInspector((prev) => ({
          ...prev,
          isLoading: false,
          error: err instanceof Error ? err.message : String(err),
        })),
      )
  }, [selectedModel, threadId])

  const openInspector = useCallback(() => {
    setInspector((prev) => ({ ...prev, open: true }))
    loadThreadMessages()
  }, [loadThreadMessages])

  const closeInspector = useCallback(() => {
    setInspector((prev) => ({ ...prev, open: false }))
  }, [])

  return {
    messages,
    models,
    selectedModel,
    setSelectedModel,
    isStreaming,
    error,
    threadId,
    inspectorOpen: inspector.open,
    inspectorSystemPrompt: inspector.systemPrompt,
    inspectorMessages: inspector.messages,
    inspectorLoading: inspector.isLoading,
    inspectorError: inspector.error,
    openInspector,
    closeInspector,
    refreshInspector: loadThreadMessages,
    bottomRef,
    sendMessage,
    startNewChat,
  }
}
