/**
 * Mermaid 图渲染：```mermaid 代码块 → SVG。
 *
 * - mermaid (~350KB gzip) 不打进主包，仅在首次遇到图时动态 import 懒加载；
 * - mermaid.render 非并发安全，用模块级 Promise 链把所有渲染串行化；
 * - 结果带当时的 code 快照：流式期间 code 变化后渲染期即可判断结果已过期
 *   （显示加载占位），effect 内不做同步 setState；
 * - 流式输出期间代码块可能不完整导致解析失败：回退展示源码，等下一轮
 *   内容变化后自动重试。
 */

import { useEffect, useState } from 'react'
import './MermaidDiagram.css'

let renderQueue: Promise<unknown> = Promise.resolve()
let diagramSeq = 0
let mermaidReady: Promise<typeof import('mermaid').default> | null = null

function loadMermaid() {
  // initialize 只执行一次；securityLevel 默认 strict，保留显式声明。
  // suppressErrorRendering：解析/绘制失败时不画「错误示意图」、直接抛异常。
  // 必须开启——mermaid 12 默认(false)在失败时把错误 SVG 画进一个直接挂在
  // document.body 上的临时 div，且异常路径不会清理它，错误 SVG 会永久残留在
  // 页面底部；开启后 mermaid 先清理临时节点再抛错，走下面的源码回退分支。
  if (!mermaidReady) {
    mermaidReady = import('mermaid').then((mod) => {
      mod.default.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        suppressErrorRendering: true,
      })
      return mod.default
    })
  }
  return mermaidReady
}

async function renderMermaid(code: string): Promise<string> {
  const mermaid = await loadMermaid()
  const id = `mermaid-diagram-${++diagramSeq}`
  const task = renderQueue.then(() => mermaid.render(id, code))
  // 失败也要继续放行队列里排队的后续渲染
  renderQueue = task.catch(() => undefined)
  const { svg } = await task
  return svg
}

/** 提取展示用的报错信息：取第一行非空文本（mermaid 报错常带冗余的版本号行）。 */
function errorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  const firstLine = message
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 0)
  return firstLine || '未知错误'
}

type RenderResult =
  | { code: string; svg: string }
  | { code: string; failed: true; error: string }

type MermaidDiagramProps = {
  code: string
}

export function MermaidDiagram({ code }: MermaidDiagramProps) {
  const [result, setResult] = useState<RenderResult | null>(null)

  useEffect(() => {
    let cancelled = false
    renderMermaid(code).then(
      (svg) => {
        if (!cancelled) setResult({ code, svg })
      },
      (error: unknown) => {
        // 控制台留全量报错（含堆栈）便于排查；界面只展示精简信息
        console.warn('[mermaid] render failed:', error)
        if (!cancelled) {
          setResult({ code, failed: true, error: errorMessage(error) })
        }
      },
    )
    return () => {
      cancelled = true
    }
  }, [code])

  // 渲染期判断结果是否属于当前 code：过期（流式中内容已变化）按未完成处理
  const current = result?.code === code ? result : null

  if (current && 'failed' in current) {
    // 解析失败（常见于流式期间的半成品代码块）：提示行 + 按普通代码块展示源码，
    // 下一轮内容变化后会自动重试
    return (
      <div className="mermaid-failed">
        <div className="mermaid-error" title={current.error}>
          图表渲染失败：{current.error}
        </div>
        <pre className="mermaid-fallback">
          <code>{code}</code>
        </pre>
      </div>
    )
  }
  if (!current) {
    return <div className="mermaid-loading">正在渲染图表…</div>
  }
  // SVG 由本地 mermaid 生成（strict 模式），非用户可控的原始 HTML
  return <div className="mermaid-diagram" dangerouslySetInnerHTML={{ __html: current.svg }} />
}
