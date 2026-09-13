/**
 * 顶部栏：标题、模型选择、状态指示，以及「查看消息 / 新对话」操作。
 */

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
}

export function ChatHeader({
  isStreaming,
  models,
  selectedModel,
  onModelChange,
  onNewChat,
  onInspect,
}: ChatHeaderProps) {
  return (
    <header className="header">
      <div className="header-brand">
        <h1>Albert Agent</h1>
        <BrandLogo />
      </div>
      <div className="header-right">
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
        <span className={`status ${isStreaming ? 'busy' : 'idle'}`}>
          {isStreaming ? '思考中…' : '在线'}
        </span>
      </div>
    </header>
  )
}
