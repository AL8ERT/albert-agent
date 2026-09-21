/**
 * 历史会话的展示辅助：把后端 ThreadMessage[] 重建为前端 ChatMessage[]，
 * 以及列表用的相对时间格式化。均为纯函数，无副作用。
 */

import type { ChatMessage, ChatPart, ThreadMessage } from '../types'

/** 本地消息自增 ID 的前缀，避免与 useChat 生成的实时消息 ID 混淆。 */
let nextHistoryId = 0

function createHistoryId(): string {
  nextHistoryId += 1
  return `history-${nextHistoryId}`
}

/**
 * 把 checkpointer 消息序列重建为前端消息列表。
 *
 * 重建规则与实时流式渲染保持一致：
 * - 跳过 hidden 消息（技能 / 子 agent 名单等框架注入内容）与 system 消息；
 * - human 消息 -> 一条 user 消息；
 * - 一轮 assistant 回复 = 一条 human 之后到下一条 human 之前的全部 ai / tool
 *   消息：ai 文本归成 text part，tool_calls 归成 tool part（结果先留空）；
 * - tool 消息按 tool_call_id 回填到先前留空的 tool part（status 一并带出），
 *   这样历史会话里的工具卡片也能显示执行结果与成败状态。
 */
export function buildChatMessages(threadMessages: ThreadMessage[]): ChatMessage[] {
  const result: ChatMessage[] = []

  /** 当前正在组装的 assistant 消息（一轮回复内的 ai/tool 都归到这里）。 */
  let currentAssistant: ChatMessage | null = null

  for (const message of threadMessages) {
    // 框架注入的隐藏消息不进入对话视图
    if (message.hidden) continue

    if (message.type === 'human') {
      // 新的一轮：结束上一条 assistant 消息，开一条 user 消息
      currentAssistant = null
      result.push({
        id: createHistoryId(),
        role: 'user',
        content: message.content,
      })
    } else if (message.type === 'ai') {
      // 工具循环会产生多条 ai 消息（中间文本 + 工具调用），都归入同一条 assistant
      if (currentAssistant === null) {
        currentAssistant = {
          id: createHistoryId(),
          role: 'assistant',
          content: '',
          parts: [],
        }
        result.push(currentAssistant)
      }
      const parts = currentAssistant.parts as ChatPart[]
      // 文本段：message_id 传 null（历史消息没有增量归组需求）
      if (message.content) {
        parts.push({
          kind: 'text',
          id: createHistoryId(),
          messageId: message.id ?? null,
          content: message.content,
        })
      }
      // 工具调用卡片：result 先置 null，等后续 tool 消息按 callId 回填
      for (const call of message.tool_calls ?? []) {
        parts.push({
          kind: 'tool',
          id: createHistoryId(),
          callId: call.id ?? '',
          name: call.name ?? '',
          args: call.args,
          result: null,
          status: null,
        })
      }
    } else if (message.type === 'tool') {
      // 工具执行结果：回填到当前 assistant 消息里对应的 tool part
      const parts = currentAssistant?.parts ?? []
      const part = parts.find(
        (item) => item.kind === 'tool' && item.callId === message.tool_call_id,
      )
      if (part && part.kind === 'tool') {
        part.result = message.content
        part.status = message.status ?? 'success'
      }
    }
    // system 消息不存于 checkpointer（系统提示词由接口单独带出），无需处理
  }

  // 收尾：仍处于 result=null 的 tool part 说明那次调用没有留下结果
  // （通常是流式过程中断），历史视图不应显示成「执行中…」，统一标注为失败
  for (const message of result) {
    if (message.role !== 'assistant') continue
    for (const part of message.parts ?? []) {
      if (part.kind === 'tool' && part.result === null) {
        part.result = '（历史记录中未包含执行结果）'
        part.status = 'error'
      }
    }
  }

  return result
}

/**
 * 列表用的相对时间：1 分钟内显示「刚刚」，1 小时内显示「x 分钟前」，
 * 24 小时内显示「x 小时前」，更早的显示具体日期（跨年带年份）。
 */
export function formatRelativeTime(iso: string): string {
  const time = new Date(iso).getTime()
  if (Number.isNaN(time)) return ''
  const diffMs = Date.now() - time
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  // 更早的会话显示日期；同一年省略年份，跨年补上避免歧义
  const date = new Date(time)
  const sameYear = date.getFullYear() === new Date().getFullYear()
  const monthDay = `${date.getMonth() + 1}月${date.getDate()}日`
  return sameYear ? monthDay : `${date.getFullYear()}年${monthDay}`
}
