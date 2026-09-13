/**
 * 单条消息：用户消息是气泡；assistant 消息按时间顺序渲染中间过程
 * （文本段 + 工具调用卡片），流式期间在最后一段文本末尾显示光标。
 */

import type { ChatMessage } from '../types'
import { ToolCallCard } from './ToolCallCard'
import './MessageItem.css'

type MessageItemProps = {
  message: ChatMessage
  isStreaming: boolean
}

export function MessageItem({ message, isStreaming }: MessageItemProps) {
  if (message.role === 'user') {
    return <div className="message user">{message.content}</div>
  }

  const parts = message.parts ?? []
  return (
    <div className="message assistant">
      {/* 还没有任何输出时先占位，保持流式光标可见 */}
      {parts.length === 0 && isStreaming && (
        <div className="assistant-text streaming" />
      )}
      {parts.map((part, index) => {
        if (part.kind === 'text') {
          // 只有最后一段文本在流式输出时显示光标
          const streaming = isStreaming && index === parts.length - 1
          return (
            <div
              key={part.id}
              className={`assistant-text${streaming ? ' streaming' : ''}`}
            >
              {part.content}
            </div>
          )
        }
        return <ToolCallCard key={part.id} part={part} />
      })}
    </div>
  )
}
