import { LayoutDashboard, MessageSquare, CalendarCheck, BrainCircuit, Headphones, Plus, Search, FileText, Database, FlaskConical } from 'lucide-react'
import { cn } from '../../lib/utils'

export type Page = 'dashboard' | 'chat' | 'planner' | 'brain' | 'voice' | 'documents' | 'data' | 'research'

interface SidebarProps {
  currentPage: Page
  onNavigate: (page: Page) => void
  onNewConversation: () => void
  connected: boolean
  onSearchOpen: () => void
}

const navItems: { page: Page; icon: typeof MessageSquare; label: string }[] = [
  { page: 'dashboard', icon: LayoutDashboard, label: 'Overview' },
  { page: 'chat', icon: MessageSquare, label: 'Chat' },
  { page: 'voice', icon: Headphones, label: 'Voice' },
  { page: 'planner', icon: CalendarCheck, label: 'Planner' },
  { page: 'documents', icon: FileText, label: 'Docs' },
  { page: 'research', icon: FlaskConical, label: 'Research' },
  { page: 'data', icon: Database, label: 'Data' },
  { page: 'brain', icon: BrainCircuit, label: 'Brain' },
]

function IconButton({ onClick, title, children }: { onClick: () => void; title: string; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className="w-9 h-9 shrink-0 rounded-full border border-white/10 flex items-center justify-center text-subtext0 hover:text-text hover:border-white/25 hover:bg-white/5 transition-colors"
    >
      {children}
    </button>
  )
}

/** Top app bar: wordmark left, segmented page switcher centre, round actions right. */
export function Sidebar({ currentPage, onNavigate, onNewConversation, connected, onSearchOpen }: SidebarProps) {
  return (
    <header className="shrink-0 px-3 sm:px-6 pt-3 sm:pt-4">
      <div className="max-w-[1400px] mx-auto flex items-center gap-3 rounded-[20px] bg-[#0b0b0b] border border-white/[0.06] pl-3 sm:pl-5 pr-2 py-2">
        {/* Brand */}
        <button
          onClick={() => onNavigate('dashboard')}
          className="flex items-center gap-2.5 shrink-0"
          aria-label="Mayday home"
        >
          <span
            className="relative w-8 h-8 rounded-[10px] bg-gradient-to-br from-[#4ade80] to-[#15803d] flex items-center justify-center shadow-[0_0_16px_rgba(34,197,94,0.35)]"
            title={connected ? 'Connected to Mayday' : 'Disconnected — retrying'}
          >
            <span className="text-black font-bold text-sm">M</span>
            <span
              className={cn(
                'absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-[#0b0b0b]',
                connected ? 'bg-green' : 'bg-red',
              )}
            />
          </span>
          <span className="hidden md:inline text-lg font-semibold tracking-tight text-text">Mayday</span>
        </button>

        {/* Segmented nav — scrolls horizontally on narrow screens */}
        <nav className="flex-1 min-w-0 flex justify-center">
          <div className="flex items-center gap-1 rounded-[14px] bg-white/[0.04] border border-white/[0.06] p-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {navItems.map(({ page, icon: Icon, label }) => {
              const active = currentPage === page
              return (
                <button
                  key={page}
                  onClick={() => onNavigate(page)}
                  aria-current={active ? 'page' : undefined}
                  title={label}
                  className={cn(
                    'flex items-center gap-2 px-3 py-2 rounded-[10px] text-xs font-medium whitespace-nowrap transition-all',
                    active
                      ? 'bg-text text-black shadow-[0_2px_10px_rgba(255,255,255,0.12)]'
                      : 'text-subtext0 hover:text-text hover:bg-white/[0.06]',
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className={cn(active ? 'inline' : 'hidden xl:inline')}>{label}</span>
                </button>
              )
            })}
          </div>
        </nav>

        {/* Actions */}
        <div className="flex items-center gap-1.5 shrink-0">
          <IconButton onClick={onSearchOpen} title="Search (Ctrl+K)">
            <Search className="h-4 w-4" />
          </IconButton>
          <IconButton onClick={onNewConversation} title="New conversation">
            <Plus className="h-4 w-4" />
          </IconButton>
          <span className="hidden sm:flex w-9 h-9 rounded-full bg-gradient-to-br from-[#86efac] to-[#16a34a] items-center justify-center text-black text-xs font-bold" aria-hidden>
            You
          </span>
        </div>
      </div>
    </header>
  )
}
