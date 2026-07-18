import { useState, useEffect } from 'react'
import { ChatProvider, useChatContext } from './context/ChatContext'
import { Sidebar, type Page } from './components/layout/Sidebar'
import { ChatPanel } from './components/chat/ChatPanel'
import { TodoPanel } from './components/todos/TodoPanel'
import { CalendarPanel } from './components/calendar/CalendarPanel'
import { BrainPanel } from './components/brain/BrainPanel'
import { DashboardPanel } from './components/dashboard/DashboardPanel'
import { SearchOverlay } from './components/search/SearchOverlay'
import { ToastContainer } from './components/ui/Toast'
import { ReminderDialog } from './components/ui/ReminderDialog'
import { VoiceMode } from './components/voice/VoiceMode'
import { DocumentPanel } from './components/documents/DocumentPanel'
import { useNotifications } from './hooks/useNotifications'
import { useLocation } from './hooks/useLocation'

function AppContent() {
  const { connected, newConversation } = useChatContext()
  const [currentPage, setCurrentPage] = useState<Page>('dashboard')
  const [searchOpen, setSearchOpen] = useState(false)

  useNotifications()
  useLocation()

  useEffect(() => {
    const handleNavigate = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail === 'dashboard' || detail === 'chat' || detail === 'todos' || detail === 'calendar' || detail === 'brain' || detail === 'voice' || detail === 'documents') {
        setCurrentPage(detail)
      }
    }
    window.addEventListener('navigate', handleNavigate)
    return () => window.removeEventListener('navigate', handleNavigate)
  }, [])

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
        {currentPage === 'dashboard' && <DashboardPanel />}
        {currentPage === 'chat' && <ChatPanel />}
        {currentPage === 'todos' && <TodoPanel />}
        {currentPage === 'calendar' && <CalendarPanel />}
        {currentPage === 'brain' && <BrainPanel />}
        {currentPage === 'documents' && <DocumentPanel />}
        {currentPage === 'voice' && <VoiceMode onExit={() => setCurrentPage('dashboard')} />}
      </div>
      <SearchOverlay
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        onNavigate={setCurrentPage}
      />
      <ToastContainer />
      <ReminderDialog />
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
