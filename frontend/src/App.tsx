/**
 * 应用根组件：把 useChat 的状态分发给各子组件。
 *
 * 结构：历史会话侧栏 + 主区（顶部栏 / 消息列表 / 输入框） + 「查看消息」弹层。
 */

import { ChatComposer } from '@/features/chat/components/ChatComposer'
import { ChatHeader } from '@/features/chat/components/ChatHeader'
import { MessageInspector } from '@/features/chat/components/MessageInspector'
import { MessageList } from '@/features/chat/components/MessageList'
import { ThreadSidebar } from '@/features/chat/components/ThreadSidebar'
import { TodoListPanel } from '@/features/chat/components/TodoListPanel'
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
    threadUsage,
    threads,
    threadsLoading,
    threadsError,
    historyOpen,
    switchingThread,
    toggleHistory,
    selectThread,
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
    todoList,
    todoPanelOpen,
    toggleTodoPanel,
  } = useChat()

  return (
    <div className="app">
      {/* 历史对话侧栏：始终挂载，由 historyOpen 控制平移显隐 */}
      <ThreadSidebar
        open={historyOpen}
        threads={threads}
        loading={threadsLoading}
        error={threadsError}
        currentThreadId={threadId}
        switching={switchingThread}
        onSelect={(id) => void selectThread(id)}
      />
      {/* 主区独立包一层，侧栏显隐时对话区宽度自适应 */}
      <div className="app-main">
        <ChatHeader
          isStreaming={isStreaming}
          models={models}
          selectedModel={selectedModel}
          onModelChange={setSelectedModel}
          onNewChat={startNewChat}
          onInspect={openInspector}
          onToggleHistory={toggleHistory}
          historyOpen={historyOpen}
          usage={threadUsage}
        />
        <MessageList
          messages={messages}
          isStreaming={isStreaming}
          error={error}
          bottomRef={bottomRef}
        />
        {/* agent 调用过 todolist 工具后常驻展示（可折叠隐藏）的待办面板 */}
        {todoList !== null && (
          <TodoListPanel
            items={todoList}
            open={todoPanelOpen}
            onToggle={toggleTodoPanel}
          />
        )}
        {/* disabled 控制流式回复期间禁止再次发送 */}
        <ChatComposer
          disabled={isStreaming}
          onSend={(text) => void sendMessage(text)}
        />
      </div>
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
