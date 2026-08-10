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
import { ArtifactPanel } from './components/research/ArtifactPanel'
import { useNotifications } from './hooks/useNotifications'
import { useLocation } from './hooks/useLocation'

function AppContent() {
  const { connected, newConversation } = useChatContext()
  const [currentPage, setCurrentPage] = useState<Page>('dashboard')
  const [searchOpen, setSearchOpen] = useState(false)
  const [artifactUrl, setArtifactUrl] = useState<string | null>(null)
  const [artifactTitle, setArtifactTitle] = useState('Artifact')

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
    const handleArtifact = (e: Event) => {
      const { url, title } = (e as CustomEvent).detail
      setArtifactUrl(url)
      setArtifactTitle(title || 'Artifact')
      setCurrentPage('chat')
    }
    window.addEventListener('open-artifact', handleArtifact)
    return () => window.removeEventListener('open-artifact', handleArtifact)
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
      <div className="flex-1 overflow-hidden relative">
        {currentPage === 'dashboard' && <DashboardPanel />}
        {currentPage === 'chat' && <ChatPanel />}
        {currentPage === 'todos' && <TodoPanel />}
        {currentPage === 'calendar' && <CalendarPanel />}
        {currentPage === 'brain' && <BrainPanel />}
        {currentPage === 'documents' && <DocumentPanel />}
        {currentPage === 'voice' && <VoiceMode onExit={() => setCurrentPage('dashboard')} />}
        {artifactUrl && currentPage === 'chat' && (
          <div className="absolute inset-y-0 right-0 w-[520px] max-w-full z-20 border-l border-surface2 shadow-2xl">
            <ArtifactPanel
              url={artifactUrl}
              title={artifactTitle}
              onClose={() => setArtifactUrl(null)}
            />
          </div>
        )}
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
