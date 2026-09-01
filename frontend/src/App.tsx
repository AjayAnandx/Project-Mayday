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
import { AnalysisPanel } from './components/data/AnalysisPanel'
import { ArtifactPanel } from './components/research/ArtifactPanel'
import { PlayerBar } from './components/player/PlayerBar'
import { PlayerQueue } from './components/player/PlayerQueue'
import { VideoPopup } from './components/player/VideoPopup'
import { PopoutManager } from './components/player/PopoutManager'
import { useMusicPlayer } from './hooks/useMusicPlayer'
import { useNotifications } from './hooks/useNotifications'
import { useLocation } from './hooks/useLocation'

function AppContent() {
  const { connected, newConversation } = useChatContext()
  const [currentPage, setCurrentPage] = useState<Page>('dashboard')
  const [searchOpen, setSearchOpen] = useState(false)
  const [artifactUrl, setArtifactUrl] = useState<string | null>(null)
  const [artifactTitle, setArtifactTitle] = useState('Artifact')
  const music = useMusicPlayer()
  const [showQueue, setShowQueue] = useState(false)
  const [showPopouts, setShowPopouts] = useState(false)
  const [videoPopupOpen, setVideoPopupOpen] = useState(false)
  const [isFavorite, setIsFavorite] = useState(false)

  // sync favorite status when track changes
  useEffect(() => {
    if (!music.current?.video_id) { setIsFavorite(false); return }
    let cancelled = false
    fetch(`/api/music/favorites/check?video_id=${encodeURIComponent(music.current.video_id)}`)
      .then(r => r.json())
      .then(j => { if (!cancelled) setIsFavorite(!!j.is_favorite) })
      .catch(() => { if (!cancelled) setIsFavorite(false) })
    return () => { cancelled = true }
  }, [music.current?.video_id])

  const handleToggleFavorite = async () => {
    if (!music.current?.video_id) return
    const wasFav = isFavorite
    setIsFavorite(!wasFav)
    try {
      const r = await fetch('/api/music/favorites/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_id: music.current.video_id,
          title: music.current.title,
          artist: music.current.artist,
          thumb: music.current.thumb,
          language: music.current.language,
          duration: music.current.duration,
        }),
      })
      const j = await r.json()
      if (r.ok && typeof j.is_favorite === 'boolean') setIsFavorite(j.is_favorite)
      else if (!r.ok) setIsFavorite(wasFav)
    } catch {
      setIsFavorite(wasFav)
    }
  }

  useEffect(() => {
    const h = (e: Event) => music.handleMusicMessage((e as CustomEvent).detail)
    window.addEventListener('mayday-music', h)
    return () => window.removeEventListener('mayday-music', h)
  }, [music.handleMusicMessage])

  useNotifications()
  useLocation()

  useEffect(() => {
    const handleNavigate = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (detail === 'dashboard' || detail === 'chat' || detail === 'todos' || detail === 'calendar' || detail === 'brain' || detail === 'voice' || detail === 'documents' || detail === 'data') {
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

  // auto-hide popout manager when all tabs closed; auto-show badge when first tab opens
  useEffect(() => {
    if (music.openPopouts.length === 0) setShowPopouts(false)
  }, [music.openPopouts.length])

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
        {currentPage === 'data' && <AnalysisPanel />}
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
        {showQueue && (
          <div className="absolute bottom-20 right-3 sm:right-4 z-20">
            <PlayerQueue
              queue={music.queue}
              currentIdx={music.currentIdx}
              onJump={music.jumpTo}
              onClear={() => { music.clearQueue(); setShowQueue(false) }}
              onClose={() => setShowQueue(false)}
            />
          </div>
        )}
        {showPopouts && music.openPopouts.length > 0 && (
          <div className="absolute bottom-20 left-3 sm:left-4 z-20">
            <PopoutManager
              tabs={music.openPopouts}
              onClose={(id)=> music.closeTab(id)}
              onFocus={(id)=> music.focusTab(id)}
              onTogglePlay={(id)=> music.toggleTabPlay(id)}
              onHide={()=> setShowPopouts(false)}
            />
          </div>
        )}
        {music.openPopouts.length > 0 && !showPopouts && (
          <button
            onClick={() => setShowPopouts(true)}
            className="absolute bottom-20 left-3 sm:left-4 z-20 px-3 py-2 rounded-full bg-green text-crust text-xs font-bold shadow-lg flex items-center gap-2 hover:bg-green/90"
          >
            <span className="w-2 h-2 rounded-full bg-crust animate-pulse" /> {music.openPopouts.length} tab{music.openPopouts.length>1?'s':''} open
          </button>
        )}
      </div>
      <PlayerBar
        current={music.current}
        queue={music.queue}
        isPlaying={music.isPlaying}
        currentTime={music.currentTime}
        duration={music.duration}
        volume={music.volume}
        repeat={music.repeat}
        expanded={music.expanded}
        needsGesture={music.needsGesture}
        playError={music.playError}
        resolving={music.resolving}
        setExpanded={music.setExpanded}
        onPlay={music.play}
        onPause={music.pause}
        onNext={music.next}
        onPrev={music.prev}
        onSeek={music.seek}
        onVolume={music.setVolume}
        onToggleRepeat={music.toggleRepeat}
        onClear={music.clearQueue}
        onToggleQueue={() => setShowQueue(v => !v)}
        showQueue={showQueue}
        videoRef={music.videoRef}
        audioRef={music.audioRef}
        onOpenYouTube={music.openYouTube as any}
        onPopout={() => {
          // try instant window.open (user gesture) — if allowed it opens separate window,
          // else fall back to in-app modal
          const res = music.popoutVideo()
          if (res.startsWith('Popup blocked')) setVideoPopupOpen(true)
        }}
        onToggleFavorite={handleToggleFavorite}
        isFavorite={isFavorite}
      />
      <VideoPopup
        track={music.current}
        isOpen={videoPopupOpen}
        onClose={() => setVideoPopupOpen(false)}
        onOpenYouTube={() => { music.openYouTube(); setVideoPopupOpen(false) }}
        onPopout={() => { music.popoutVideo(); setVideoPopupOpen(false) }}
      />
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
