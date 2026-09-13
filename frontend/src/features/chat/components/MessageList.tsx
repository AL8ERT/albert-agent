/**
 * 消息列表：空状态、消息气泡、错误提示与滚动锚点。
 */

import type { RefObject } from 'react'
import type { ChatMessage } from '../types'
import { MessageItem } from './MessageItem'
import './MessageList.css'

type MessageListProps = {
  messages: ChatMessage[]
  isStreaming: boolean
  error: string | null
  /** 列表底部的空 div，用于自动滚动到底 */
  bottomRef: RefObject<HTMLDivElement | null>
}

export function MessageList({
  messages,
  isStreaming,
  error,
  bottomRef,
}: MessageListProps) {
  return (
    <main className="messages">
      {messages.length === 0 && (
        <div className="empty">
          <p>你好，我是 Albert。</p>
          <p>输入消息，开始对话。</p>
        </div>
      )}

      {messages.map((message, index) => (
        <MessageItem
          key={message.id}
          message={message}
          // 只有最后一条 assistant 消息在流式输出时才显示光标
          isStreaming={
            isStreaming &&
            message.role === 'assistant' &&
            index === messages.length - 1
          }
        />
      ))}

      {error && <div className="error-banner">{error}</div>}
      {/* 滚动锚点：useChat 在 messages 变化时调用 scrollIntoView */}
      <div ref={bottomRef} />
    </main>
  )
}
