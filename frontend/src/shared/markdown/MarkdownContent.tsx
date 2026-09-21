/**
 * Markdown 渲染组件：assistant 消息正文统一走这里。
 *
 * - remark-gfm：表格 / 任务列表 / 删除线；
 * - remark-math + rehype-katex：$...$ 行内公式与 $$...$$ 块级公式（KaTeX）；
 * - ```mermaid 代码块交给 MermaidDiagram 懒加载渲染，其余代码块用深色底样式；
 * - React.memo 按内容缓存：流式期间只有内容变化的那条消息会重新解析，
 *   历史消息不会重复走 unified 管线。
 *
 * 安全：react-markdown 默认不渲染原始 HTML（未加 rehype-raw），
 * mermaid SVG 在 strict 安全级别下本地生成，均无 XSS 注入面。
 */

import { memo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import { MermaidDiagram } from './MermaidDiagram'
import './MarkdownContent.css'
import 'katex/dist/katex.min.css'

/** 从 code 节点的 className 里提取语言标识，如 "language-mermaid" → "mermaid" */
function languageOf(className: string | undefined): string | null {
  const match = /language-([\w-]+)/.exec(className ?? '')
  return match ? match[1] : null
}

const components: Components = {
  // 默认 <pre> 只包一层，块级样式由下方 code 组件自己接管
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const language = languageOf(className)
    const text = String(children).replace(/\n$/, '')

    if (language === 'mermaid') {
      return <MermaidDiagram code={text} />
    }
    if (language) {
      return (
        <pre className="md-code-block">
          <code>{text}</code>
        </pre>
      )
    }
    return <code className="md-inline-code">{children}</code>
  },
  // 链接在新标签页打开，避免应用内跳转丢会话
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  ),
}

type MarkdownContentProps = {
  content: string
}

export const MarkdownContent = memo(function MarkdownContent({
  content,
}: MarkdownContentProps) {
  return (
    <div className="md-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
})
