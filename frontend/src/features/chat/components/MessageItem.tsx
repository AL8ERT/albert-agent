/**
 * 单条消息：用户消息是纯文本气泡；assistant 消息按时间顺序渲染中间过程
 * （思维链折叠块 + Markdown 文本段 + 工具调用卡片），流式期间在最后一段
 * 文本末尾显示光标。
 */

import type { ChatMessage } from '../types'
import { formatUsageLine } from '../lib/usage'
import { ReasoningBlock } from './ReasoningBlock'
import { ToolCallCard } from './ToolCallCard'
import { MarkdownContent } from '@/shared/markdown/MarkdownContent'
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
        if (part.kind === 'reasoning') {
          // 思维链块：流式中且是最后一个 part 时视为仍在思考（展开 + 动画）
          return (
            <ReasoningBlock
              key={part.id}
              part={part}
              streaming={isStreaming && index === parts.length - 1}
            />
          )
        }
        if (part.kind === 'text') {
          // 只有最后一段文本在流式输出时显示光标
          const streaming = isStreaming && index === parts.length - 1
          return (
            <div
              key={part.id}
              className={`assistant-text${streaming ? ' streaming' : ''}`}
            >
              <MarkdownContent content={part.content} />
            </div>
          )
        }
        return <ToolCallCard key={part.id} part={part} />
      })}
      {/* 流结束后由 done 事件回填的本轮 token 用量 */}
      {message.usage && (
        <div className="assistant-usage">{formatUsageLine(message.usage)}</div>
      )}
    </div>
  )
}
