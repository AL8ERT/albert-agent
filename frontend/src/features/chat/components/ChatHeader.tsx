/**
 * 顶部栏：标题、模型选择、状态指示，以及「查看消息 / 新对话」操作。
 */

import type { TokenUsage } from '../types'
import { formatThreadUsage } from '../lib/usage'
import { BrandLogo } from './BrandLogo'
import { ModelSelector } from './ModelSelector'
import './ChatHeader.css'

type ChatHeaderProps = {
  isStreaming: boolean
  models: string[]
  selectedModel: string
  onModelChange: (model: string) => void
  onNewChat: () => void
  /** 打开 checkpointer 消息查看面板 */
  onInspect: () => void
  /** 打开/收起历史会话侧栏 */
  onToggleHistory: () => void
  /** 历史侧栏是否处于打开状态（按钮高亮反馈） */
  historyOpen: boolean
  /** 当前会话的累计 token 用量（至少完成一轮对话后才有值） */
  usage: TokenUsage | null
}

export function ChatHeader({
  isStreaming,
  models,
  selectedModel,
  onModelChange,
  onNewChat,
  onInspect,
  onToggleHistory,
  historyOpen,
  usage,
}: ChatHeaderProps) {
  return (
    <header className="header">
      <div className="header-brand">
        <h1>Albert Agent</h1>
        <BrandLogo />
      </div>
      <div className="header-right">
        {/* 历史对话侧栏开关（侧栏打开时按钮高亮） */}
        <button
          className={`header-button${historyOpen ? ' active' : ''}`}
          type="button"
          disabled={isStreaming}
          onClick={onToggleHistory}
        >
          历史
        </button>
        {/* 查看当前线程在 checkpointer 中的消息（含系统提示词） */}
        <button className="header-button" type="button" onClick={onInspect}>
          查看消息
        </button>
        {/* 流式回复中不允许切换会话 */}
        <button
          className="header-button"
          type="button"
          disabled={isStreaming}
          onClick={onNewChat}
        >
          新对话
        </button>
        <ModelSelector
          models={models}
          value={selectedModel}
          disabled={isStreaming}
          onChange={onModelChange}
        />
        {/* 会话累计 token 用量（输入 / 缓存 / 输出） */}
        {usage && (
          <span className="usage-badge" title="本会话累计 token 用量（输入 / 缓存命中 / 输出）">
            {formatThreadUsage(usage)}
          </span>
        )}
        <span className={`status ${isStreaming ? 'busy' : 'idle'}`}>
          {isStreaming ? '思考中…' : '在线'}
        </span>
      </div>
    </header>
  )
}
