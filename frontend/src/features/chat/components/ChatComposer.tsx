/**
 * 输入框组件：Enter 发送，Shift+Enter 换行。
 */

import { useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import './ChatComposer.css'

type ChatComposerProps = {
  /** 流式回复中禁用输入，避免并发发送 */
  disabled: boolean
  onSend: (text: string) => void
}

export function ChatComposer({ disabled, onSend }: ChatComposerProps) {
  const [input, setInput] = useState('')

  /** 校验非空后回调发送并清空输入框。 */
  function submit() {
    if (disabled || input.trim() === '') return
    onSend(input)
    setInput('')
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    submit()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // isComposing 用于跳过中文输入法选词时的 Enter，避免误发送
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="给 Albert 发消息…（Enter 发送，Shift+Enter 换行）"
        rows={1}
        autoFocus
      />
      <button type="submit" disabled={disabled || input.trim() === ''}>
        发送
      </button>
    </form>
  )
}
