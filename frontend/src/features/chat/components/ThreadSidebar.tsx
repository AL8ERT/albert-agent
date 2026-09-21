/**
 * 历史会话侧栏：列出后端保存的历史对话（标题 / 相对时间 / 消息数），
 * 点击切换到对应会话；当前会话高亮，流式回复期间禁止切换。
 */

import type { ThreadSummary } from '../types'
import { formatRelativeTime } from '../lib/history'
import './ThreadSidebar.css'

type ThreadSidebarProps = {
  /** 是否显示侧栏（由 useChat 的 historyOpen 控制） */
  open: boolean
  /** 历史会话摘要列表（后端按最近活跃倒序） */
  threads: ThreadSummary[]
  /** 列表加载中 */
  loading: boolean
  /** 列表加载失败的错误信息 */
  error: string | null
  /** 当前会话 ID：列表中对应项高亮 */
  currentThreadId: string
  /** 正在切换会话（切换期间列表整体禁用） */
  switching: boolean
  /** 点击某条会话：切换到该会话 */
  onSelect: (threadId: string) => void
}

export function ThreadSidebar({
  open,
  threads,
  loading,
  error,
  currentThreadId,
  switching,
  onSelect,
}: ThreadSidebarProps) {
  return (
    <aside className={`thread-sidebar${open ? ' open' : ''}`}>
      <div className="thread-sidebar-header">
        <span>历史对话</span>
        {/* 条目数徽标：让用户不展开也能从收起状态感知有多少会话 */}
        {threads.length > 0 && (
          <span className="thread-count">{threads.length}</span>
        )}
      </div>

      <div className="thread-sidebar-body">
        {loading && <div className="thread-sidebar-hint">加载中…</div>}
        {error && <div className="thread-sidebar-hint error">{error}</div>}
        {!loading && !error && threads.length === 0 && (
          // 后端未配置 PostgreSQL 时列表恒为空，给出可理解的提示
          <div className="thread-sidebar-hint">暂无历史对话</div>
        )}

        {threads.map((thread) => (
          <button
            key={thread.thread_id}
            type="button"
            className={`thread-item${
              thread.thread_id === currentThreadId ? ' active' : ''
            }`}
            // 切换中禁止重复点击；当前会话点击无操作（避免无谓加载）
            disabled={switching || thread.thread_id === currentThreadId}
            onClick={() => onSelect(thread.thread_id)}
          >
            <div className="thread-item-title">{thread.title}</div>
            <div className="thread-item-meta">
              <span>{formatRelativeTime(thread.updated_at)}</span>
              <span>{thread.message_count} 条消息</span>
            </div>
          </button>
        ))}
      </div>
    </aside>
  )
}
