/**
 * 工具调用卡片：展示工具名、入参，以及执行中 / 执行结果。
 */

import type { ToolPart } from '../types'
import './ToolCallCard.css'

type ToolCallCardProps = {
  part: ToolPart
}

/** 入参格式化为 JSON；无参数时返回空串（不渲染参数区）。 */
function formatArgs(args: unknown): string {
  if (args === undefined || args === null) return ''
  if (typeof args === 'object' && !Array.isArray(args) && Object.keys(args).length === 0) {
    return ''
  }
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return String(args)
  }
}

export function ToolCallCard({ part }: ToolCallCardProps) {
  // result 为 null 表示后端还没返回 tool_result
  const pending = part.result === null
  const failed = part.status === 'error'
  const argsText = formatArgs(part.args)

  return (
    <div className={`tool-call${failed ? ' failed' : ''}`}>
      <div className="tool-call-header">
        <span className="tool-call-name">{part.name || 'tool'}</span>
        <span className="tool-call-status">
          {pending ? '执行中…' : failed ? '失败' : '完成'}
        </span>
      </div>
      {argsText && <pre className="tool-call-args">{argsText}</pre>}
      {pending ? (
        <p className="tool-call-pending">等待工具返回…</p>
      ) : (
        <pre className="tool-call-result">{part.result || '(空)'}</pre>
      )}
    </div>
  )
}
