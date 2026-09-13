/**
 * 「查看消息」面板：展示当前线程在 checkpointer 中的完整消息，
 * 以及创建 agent 时配置、但不写入 checkpointer 的系统提示词。
 *
 * 支持：遮罩点击关闭、Esc 关闭、刷新重新拉取。
 */

import { useEffect } from 'react'
import type { ThreadMessage } from '../types'
import './MessageInspector.css'

type MessageInspectorProps = {
  open: boolean
  threadId: string
  systemPrompt: string | null
  messages: ThreadMessage[]
  isLoading: boolean
  error: string | null
  onRefresh: () => void
  onClose: () => void
}

export function MessageInspector({
  open,
  threadId,
  systemPrompt,
  messages,
  isLoading,
  error,
  onRefresh,
  onClose,
}: MessageInspectorProps) {
  // 面板打开期间监听 Esc 关闭；关闭后移除监听
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  // 关闭状态下不渲染任何内容
  if (!open) return null

  return (
    // 点击遮罩关闭；内部区域阻止冒泡，避免点内容时误关
    <div className="inspector-overlay" onClick={onClose}>
      <section
        className="inspector"
        role="dialog"
        aria-modal="true"
        aria-label="Checkpointer 消息列表"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="inspector-header">
          <div>
            <h2>Checkpointer 消息</h2>
            <p className="inspector-thread">thread: {threadId}</p>
          </div>
          <div className="inspector-actions">
            <button
              type="button"
              className="inspector-button"
              disabled={isLoading}
              onClick={onRefresh}
            >
              刷新
            </button>
            <button type="button" className="inspector-button" onClick={onClose}>
              关闭
            </button>
          </div>
        </header>

        <div className="inspector-body">
          {isLoading && <p className="inspector-hint">加载中…</p>}
          {!isLoading && error && <p className="inspector-error">{error}</p>}

          {/* 系统提示词不存 checkpointer，由后端配置单独返回后置顶展示 */}
          {systemPrompt && (
            <article className="inspector-message">
              <span className="inspector-role role-system">system</span>
              <pre className="inspector-content">{systemPrompt}</pre>
              <p className="inspector-note">
                不在 checkpointer 中，调用模型时注入
              </p>
            </article>
          )}

          {!isLoading && !error && messages.length === 0 && (
            <p className="inspector-hint">该线程还没有消息。</p>
          )}

          {messages.map((message, index) => (
            // 只读列表，index 作为 key 即可
            <article className="inspector-message" key={index}>
              <span className={`inspector-role role-${message.type}`}>
                {message.type}
              </span>
              <pre className="inspector-content">{message.content || '(空)'}</pre>
              {/* AI 发起的工具调用以 JSON 展示 */}
              {message.tool_calls && message.tool_calls.length > 0 && (
                <pre className="inspector-tools">
                  {JSON.stringify(message.tool_calls, null, 2)}
                </pre>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
