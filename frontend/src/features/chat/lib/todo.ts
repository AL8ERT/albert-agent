/**
 * 待办事项的解析与展示辅助：从 todolist 工具调用的入参中解析条目列表、
 * 在重建的历史消息中定位最新一次成功调用，以及优先级 / 状态的中文标签。
 * 均为纯函数，无副作用。
 */

import type { ChatMessage, TodoItem, TodoPriority, TodoStatus } from '../types'

/** 后端 todolist 工具名（tool_call / tool_result 事件里的 name）。 */
export const TODOLIST_TOOL_NAME = 'todolist'

/** 优先级的中文标签。 */
export const TODO_PRIORITY_LABELS: Record<TodoPriority, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

/** 状态的中文标签。 */
export const TODO_STATUS_LABELS: Record<TodoStatus, string> = {
  pending: '未开始',
  in_progress: '进行中',
  completed: '已完成',
  abandoned: '已放弃',
}

const PRIORITIES: readonly TodoPriority[] = ['low', 'medium', 'high']
const STATUSES: readonly TodoStatus[] = [
  'pending',
  'in_progress',
  'completed',
  'abandoned',
]

/**
 * 解析 todolist 工具调用的 args（unknown）为待办条目数组。
 * 不是 todolist 的入参结构（缺 todos 数组）时返回 null；
 * 个别畸形条目直接跳过（后端成功结果隐含已做过校验，这里是防御）。
 */
export function parseTodoArgs(args: unknown): TodoItem[] | null {
  if (typeof args !== 'object' || args === null) return null
  const todos = (args as { todos?: unknown }).todos
  if (!Array.isArray(todos)) return null

  const items: TodoItem[] = []
  for (const todo of todos) {
    if (typeof todo !== 'object' || todo === null) continue
    const { content, priority, status } = todo as Record<string, unknown>
    if (typeof content !== 'string' || content.trim() === '') continue
    if (!PRIORITIES.includes(priority as TodoPriority)) continue
    if (!STATUSES.includes(status as TodoStatus)) continue
    items.push({
      content: content.trim(),
      priority: priority as TodoPriority,
      status: status as TodoStatus,
    })
  }
  return items
}

/**
 * 在（实时或历史重建的）消息列表里找最后一次成功执行的 todolist 调用入参，
 * 作为当前待办列表恢复；从未成功调用过时返回 null。
 */
export function findLatestTodoArgs(messages: ChatMessage[]): TodoItem[] | null {
  let result: TodoItem[] | null = null
  for (const message of messages) {
    for (const part of message.parts ?? []) {
      if (part.kind !== 'tool' || part.name !== TODOLIST_TOOL_NAME) continue
      // error 结果（含历史里缺失结果的调用）不能作为当前状态
      if (part.status === 'error') continue
      const items = parseTodoArgs(part.args)
      if (items !== null) result = items
    }
  }
  return result
}
