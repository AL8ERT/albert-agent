/**
 * token 用量展示格式化（消息底部明细与顶栏会话累计共用）。
 */

import type { TokenUsage } from '../types'

/** 千分位格式化（toLocaleString 跟随系统语言）。 */
function formatNumber(value: number): string {
  return value.toLocaleString()
}

/**
 * 缓存命中率：命中 /（未命中 + 命中）；没有任何输入 token 时返回 null。
 * 输入的展示口径已不含缓存，分母需要把命中量加回去。
 */
function formatCacheRate(usage: TokenUsage): string | null {
  const totalInput = usage.input_tokens + usage.cached_tokens
  if (totalInput <= 0) {
    return null
  }
  return `${((usage.cached_tokens / totalInput) * 100).toFixed(1)}%`
}

/** 缓存段文案：数量 + 命中率，如「缓存命中 1,024 (81.4%)」。 */
function formatCachePart(usage: TokenUsage, label: string): string {
  const rate = formatCacheRate(usage)
  return `${label} ${formatNumber(usage.cached_tokens)}${rate ? ` (${rate})` : ''}`
}

/** assistant 消息底部一行小字：输入（不含缓存）/ 缓存命中（带命中率）/ 输出（缓存为 0 时省略命中段）。 */
export function formatUsageLine(usage: TokenUsage): string {
  const parts = [`输入 ${formatNumber(usage.input_tokens)}`]
  if (usage.cached_tokens > 0) {
    parts.push(formatCachePart(usage, '缓存命中'))
  }
  parts.push(`输出 ${formatNumber(usage.output_tokens)}`)
  return parts.join(' · ')
}

/** 顶栏会话累计的紧凑形式（缓存恒展示，保持宽度稳定）。 */
export function formatThreadUsage(usage: TokenUsage): string {
  return `本会话 输入 ${formatNumber(usage.input_tokens)} · ${formatCachePart(usage, '缓存')} · 输出 ${formatNumber(usage.output_tokens)}`
}
