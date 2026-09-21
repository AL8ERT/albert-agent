/**
 * useChat：聊天页面的核心状态管理。
 *
 * 负责：
 * - 加载模型列表、维护当前选中的模型；
 * - 维护当前 threadId（会话标识，多轮对话复用同一个 ID）；
 * - 发送消息并把 SSE token 增量写入最后一条 assistant 消息；
 * - 历史会话：拉取会话摘要列表、点击切换（重建消息与累计用量）；
 * - 「查看消息」面板的打开/关闭与数据加载（读取后端 checkpointer）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchModels,
  fetchThreadMessages,
  fetchThreadSummaries,
  streamChat,
} from '../api/chatApi'
import { buildChatMessages } from '../lib/history'
import type {
  ChatMessage,
  ChatPart,
  ThreadMessage,
  ThreadSummary,
  TokenUsage,
} from '../types'

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
  // 显式标注 string：crypto.randomUUID() 的返回类型是 UUID 模板字面量，
  // 不标注的话 setThreadId 普通字符串会类型不兼容
  const [threadId, setThreadId] = useState<string>(() => crypto.randomUUID())
  const [models, setModels] = useState<string[]>([])
  const [selectedModel, setSelectedModel] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 当前会话的累计 token 用量：每轮流结束由 done 事件的 total_usage 更新
  const [threadUsage, setThreadUsage] = useState<TokenUsage | null>(null)
  const [inspector, setInspector] = useState(INITIAL_INSPECTOR_STATE)
  // 历史会话列表（来自后端审计表聚合；未配置 PostgreSQL 时恒为空）
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [threadsLoading, setThreadsLoading] = useState(false)
  const [threadsError, setThreadsError] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  // 切换历史会话时的消息加载状态（列表本身用 threadsLoading）
  const [switchingThread, setSwitchingThread] = useState(false)
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

  /** 拉取历史会话列表（打开侧栏与每轮流结束后调用）。 */
  const loadThreads = useCallback(async () => {
    setThreadsLoading(true)
    setThreadsError(null)
    try {
      setThreads(await fetchThreadSummaries())
    } catch (err: unknown) {
      // 列表加载失败不阻塞聊天，只在侧栏内展示错误提示
      setThreadsError(err instanceof Error ? err.message : String(err))
    } finally {
      setThreadsLoading(false)
    }
  }, [])

  /** 打开/收起历史侧栏；每次打开都重新拉取，反映最新会话状态。 */
  const toggleHistory = useCallback(() => {
    if (isStreaming) return
    setHistoryOpen((open) => {
      if (!open) void loadThreads()
      return !open
    })
  }, [isStreaming, loadThreads])

  /**
   * 切换到某个历史会话：拉取该线程在 checkpointer 中的消息并重建为
   * 前端消息列表（含工具卡片结果回填），同时恢复会话累计用量。
   * 之后继续发消息即在该会话上下文中进行。
   */
  const selectThread = useCallback(
    async (threadIdToSelect: string) => {
      // 流式回复 / 正在切换时不允许再切，避免状态交错
      if (isStreaming || switchingThread) return
      setSwitchingThread(true)
      setHistoryOpen(false) // 点击后收起侧栏，回到对话视图
      try {
        const data = await fetchThreadMessages(
          threadIdToSelect,
          selectedModel || undefined,
        )
        setThreadId(threadIdToSelect)
        setMessages(buildChatMessages(data.messages))
        setThreadUsage(data.total_usage ?? null)
        setError(null)
      } catch (err: unknown) {
        // 切换失败保留原会话内容，仅提示错误
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setSwitchingThread(false)
      }
    },
    [isStreaming, selectedModel, switchingThread],
  )

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
        const result = await streamChat(content, {
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
          // 同一条 LLM 消息的思维链增量追加到同一块；换消息则新开一块
          // （归组逻辑与 onToken 同构，只是 kind 不同、与文本块互相独立）
          onReasoning: (token, messageId) => {
            updateParts((parts) => {
              const last = parts[parts.length - 1]
              if (
                last?.kind === 'reasoning' &&
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
                  kind: 'reasoning',
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
        // 流结束：把本轮用量挂到 assistant 消息底部，并更新会话累计
        if (result.turnUsage) {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantMessage.id
                ? { ...message, usage: result.turnUsage }
                : message,
            ),
          )
        }
        if (result.totalUsage) {
          setThreadUsage(result.totalUsage)
        }
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
        // 静默刷新历史列表：当前会话的标题 / 时间 / 消息数可能有更新
        void loadThreads()
      }
    },
    [isStreaming, selectedModel, threadId, loadThreads],
  )

  /** 开始新对话：换新的 threadId 并清空消息与用量，旧会话历史仍保留在后端。 */
  const startNewChat = useCallback(() => {
    if (isStreaming) return
    setThreadId(crypto.randomUUID())
    setMessages([])
    setError(null)
    setThreadUsage(null)
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
    threadUsage,
    threads,
    threadsLoading,
    threadsError,
    historyOpen,
    switchingThread,
    toggleHistory,
    selectThread,
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
