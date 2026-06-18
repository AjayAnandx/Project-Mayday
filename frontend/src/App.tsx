import { useState, useEffect } from 'react'
import { ChatProvider, useChatContext } from './context/ChatContext'
import { Sidebar, type Page } from './components/layout/Sidebar'
import { ChatPanel } from './components/chat/ChatPanel'
import { TodoPanel } from './components/todos/TodoPanel'
import { CalendarPanel } from './components/calendar/CalendarPanel'
import { BrainPanel } from './components/brain/BrainPanel'
import { SearchOverlay } from './components/search/SearchOverlay'

function AppContent() {
  const { connected, newConversation } = useChatContext()
  const [currentPage, setCurrentPage] = useState<Page>('chat')
  const [searchOpen, setSearchOpen] = useState(false)

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [])

  return (
    <div className="flex flex-col h-screen bg-crust text-text">
      <Sidebar
        currentPage={currentPage}
        onNavigate={setCurrentPage}
        onNewConversation={newConversation}
        connected={connected}
        onSearchOpen={() => setSearchOpen(true)}
      />
      <div className="flex-1 overflow-hidden">
        {currentPage === 'chat' && <ChatPanel />}
        {currentPage === 'todos' && <TodoPanel />}
        {currentPage === 'calendar' && <CalendarPanel />}
        {currentPage === 'brain' && <BrainPanel />}
      </div>
      <SearchOverlay
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        onNavigate={setCurrentPage}
      />
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
