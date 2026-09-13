/**
 * 应用根组件：把 useChat 的状态分发给各子组件。
 *
 * 结构：顶部栏（模型/操作） + 消息列表 + 输入框 + 「查看消息」弹层。
 */

import { ChatComposer } from '@/features/chat/components/ChatComposer'
import { ChatHeader } from '@/features/chat/components/ChatHeader'
import { MessageInspector } from '@/features/chat/components/MessageInspector'
import { MessageList } from '@/features/chat/components/MessageList'
import { useChat } from '@/features/chat/hooks/useChat'
import './App.css'

function App() {
  const {
    messages,
    models,
    selectedModel,
    setSelectedModel,
    isStreaming,
    error,
    threadId,
    inspectorOpen,
    inspectorSystemPrompt,
    inspectorMessages,
    inspectorLoading,
    inspectorError,
    openInspector,
    closeInspector,
    refreshInspector,
    bottomRef,
    sendMessage,
    startNewChat,
  } = useChat()

  return (
    <div className="app">
      <ChatHeader
        isStreaming={isStreaming}
        models={models}
        selectedModel={selectedModel}
        onModelChange={setSelectedModel}
        onNewChat={startNewChat}
        onInspect={openInspector}
      />
      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        error={error}
        bottomRef={bottomRef}
      />
      {/* disabled 控制流式回复期间禁止再次发送 */}
      <ChatComposer disabled={isStreaming} onSend={(text) => void sendMessage(text)} />
      {/* 弹层始终挂载，由 open 控制显隐 */}
      <MessageInspector
        open={inspectorOpen}
        threadId={threadId}
        systemPrompt={inspectorSystemPrompt}
        messages={inspectorMessages}
        isLoading={inspectorLoading}
        error={inspectorError}
        onRefresh={refreshInspector}
        onClose={closeInspector}
      />
    </div>
  )
}

export default App
