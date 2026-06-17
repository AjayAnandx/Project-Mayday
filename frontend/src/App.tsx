import { useState } from 'react'
import { ChatProvider, useChatContext } from './context/ChatContext'
import { Sidebar, type Page } from './components/layout/Sidebar'
import { ChatPanel } from './components/chat/ChatPanel'
import { TodoPanel } from './components/todos/TodoPanel'
import { CalendarPanel } from './components/calendar/CalendarPanel'
import { BrainPanel } from './components/brain/BrainPanel'

function AppContent() {
  const { connected, newConversation } = useChatContext()
  const [currentPage, setCurrentPage] = useState<Page>('chat')

  return (
    <div className="flex flex-col h-screen bg-crust text-text">
      <Sidebar
        currentPage={currentPage}
        onNavigate={setCurrentPage}
        onNewConversation={newConversation}
        connected={connected}
      />
      <div className="flex-1 overflow-hidden">
        {currentPage === 'chat' && <ChatPanel />}
        {currentPage === 'todos' && <TodoPanel />}
        {currentPage === 'calendar' && <CalendarPanel />}
        {currentPage === 'brain' && <BrainPanel />}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <ChatProvider>
      <AppContent />
    </ChatProvider>
  )
}
