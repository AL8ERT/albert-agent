/**
 * 待办事项面板：agent 调用过 todolist 工具后常驻展示在消息区与输入框之间。
 * 头部显示进度摘要，点击可折叠 / 展开（「隐藏」即折叠成一行头部）；
 * 条目按状态图标 + 事项名 + 优先级徽标展示，已完成 / 已放弃划线淡化。
 */

import type { TodoItem, TodoStatus } from '../types'
import { TODO_PRIORITY_LABELS } from '../lib/todo'
import './TodoListPanel.css'

type TodoListPanelProps = {
  items: TodoItem[]
  open: boolean
  onToggle: () => void
}

const STATUS_ICONS: Record<TodoStatus, string> = {
  pending: '○',
  in_progress: '◐',
  completed: '✓',
  abandoned: '✕',
}

export function TodoListPanel({ items, open, onToggle }: TodoListPanelProps) {
  const completed = items.filter((item) => item.status === 'completed').length

  return (
    <section className="todo-panel" aria-label="待办事项">
      <button
        type="button"
        className="todo-header"
        onClick={onToggle}
        aria-expanded={open}
      >
        <span className="todo-title">待办事项</span>
        <span className="todo-progress">
          {items.length === 0 ? '已清空' : `${completed}/${items.length} 已完成`}
        </span>
        <span className="todo-chevron">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <ul className="todo-list">
          {items.length === 0 && <li className="todo-empty">暂无待办事项</li>}
          {items.map((item, index) => (
            <li key={index} className={`todo-item ${item.status}`}>
              <span className="todo-status-icon" title={item.status}>
                {STATUS_ICONS[item.status]}
              </span>
              <span className="todo-content">{item.content}</span>
              <span className={`todo-priority ${item.priority}`}>
                {TODO_PRIORITY_LABELS[item.priority]}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
