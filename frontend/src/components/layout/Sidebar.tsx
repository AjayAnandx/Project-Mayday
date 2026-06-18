import { MessageSquare, ListTodo, CalendarDays, BrainCircuit, Plus, Search } from 'lucide-react'
import { cn } from '../../lib/utils'

export type Page = 'chat' | 'todos' | 'calendar' | 'brain'

interface SidebarProps {
  currentPage: Page
  onNavigate: (page: Page) => void
  onNewConversation: () => void
  connected: boolean
  onSearchOpen: () => void
}

const navItems: { page: Page; icon: typeof MessageSquare; label: string }[] = [
  { page: 'chat', icon: MessageSquare, label: 'Chat' },
  { page: 'todos', icon: ListTodo, label: 'Todos' },
  { page: 'calendar', icon: CalendarDays, label: 'Calendar' },
  { page: 'brain', icon: BrainCircuit, label: 'Brain' },
]

export function Sidebar({ currentPage, onNavigate, onNewConversation, connected, onSearchOpen }: SidebarProps) {
  return (
    <div className="flex items-center justify-center pt-4 pb-2 shrink-0">
      <div className="flex items-center gap-2 bg-black/60 border border-green/15 rounded-full px-3 py-2 shadow-lg shadow-green/5">
        <div className="flex items-center gap-2 pr-2 border-r border-green/15">
          <div className="w-7 h-7 rounded-full bg-green flex items-center justify-center">
            <span className="text-crust font-bold text-xs">M</span>
          </div>
          <div
            className={cn(
              'w-2 h-2 rounded-full',
              connected ? 'bg-green' : 'bg-red',
            )}
          />
        </div>

        <div className="flex items-center gap-0.5">
          {navItems.map(({ page, icon: Icon, label }) => (
            <button
              key={page}
              onClick={() => onNavigate(page)}
              className={cn(
                'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs font-medium transition-all',
                currentPage === page
                  ? 'bg-green/10 text-green shadow-sm'
                  : 'text-overlay0 hover:text-text hover:bg-white/5',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1 pl-2 border-l border-green/15">
          <button
            onClick={onSearchOpen}
            className="flex items-center justify-center w-7 h-7 rounded-full text-overlay0 hover:text-text hover:bg-surface0/50 transition-colors"
            title="Search (Ctrl+K)"
          >
            <Search className="h-4 w-4" />
          </button>
          <button
            onClick={onNewConversation}
            className="flex items-center justify-center w-7 h-7 rounded-full text-overlay0 hover:text-text hover:bg-surface0/50 transition-colors"
            title="New conversation"
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
