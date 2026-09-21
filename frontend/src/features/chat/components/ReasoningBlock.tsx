/**
 * 思维链块：可折叠面板。
 * 流式期间展开实时显示思考内容（头部「思考中…」），本轮思考结束后自动折叠
 * 成一行摘要（「已深度思考」），点击头部随时手动展开 / 收起。
 */

import { useState } from 'react'
import type { ReasoningPart } from '../types'
import { MarkdownContent } from '@/shared/markdown/MarkdownContent'
import './ReasoningBlock.css'

type ReasoningBlockProps = {
  part: ReasoningPart
  /** 该块是否还在接收增量（流式中且是 assistant 消息的最后一个 part） */
  streaming: boolean
}

export function ReasoningBlock({ part, streaming }: ReasoningBlockProps) {
  // 挂载时跟随流式状态：流式中的块默认展开
  const [open, setOpen] = useState(streaming)
  // streaming 变 false（本轮思考结束）时自动折叠一次；之后交还用户手动控制。
  // 采用 React 官方「渲染期间调整 state」模式（记录上一次的 streaming 对比），
  // 避免在 effect 里同步 setState 触发级联渲染
  const [wasStreaming, setWasStreaming] = useState(streaming)
  if (streaming !== wasStreaming) {
    setWasStreaming(streaming)
    if (!streaming) setOpen(false)
  }

  return (
    <div className={`reasoning-block${open ? ' open' : ''}`}>
      <button
        type="button"
        className="reasoning-header"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className={`reasoning-title${streaming ? ' thinking' : ''}`}>
          {streaming ? '思考中…' : '已深度思考'}
        </span>
        <span className="reasoning-chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="reasoning-body">
          <MarkdownContent content={part.content} />
        </div>
      )}
    </div>
  )
}
