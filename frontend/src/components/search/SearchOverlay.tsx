import { useState, useEffect, useRef } from 'react'
import { Search, ListTodo, CalendarDays, MessageSquare, BrainCircuit, History, Loader2, X } from 'lucide-react'
import { useSearch } from '../../hooks/useSearch'
import type { SearchResults } from '../../types/search'

interface SearchOverlayProps {
  open: boolean
  onClose: () => void
  onNavigate: (page: 'chat' | 'todos' | 'calendar' | 'brain') => void
}

export function SearchOverlay({ open, onClose, onNavigate }: SearchOverlayProps) {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const { results, loading } = useSearch(query)

  useEffect(() => {
    if (open) {
      setQuery('')
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  if (!open) return null

  const sections: {
    key: keyof SearchResults
    icon: typeof Search
    label: string
    page: 'chat' | 'todos' | 'calendar' | 'brain'
    render: (item: any) => string
  }[] = [
    { key: 'todos', icon: ListTodo, label: 'Todos', page: 'todos', render: (t) => `${t.title} — ${t.snippet}` },
    { key: 'events', icon: CalendarDays, label: 'Events', page: 'calendar', render: (e) => `${e.title} — ${e.snippet}` },
    { key: 'conversations', icon: MessageSquare, label: 'Conversations', page: 'chat', render: (c) => `${c.title} (${c.date})` },
    { key: 'graph_nodes', icon: BrainCircuit, label: 'Memories', page: 'brain', render: (n) => `[${n.type}] ${n.label}` },
    { key: 'operations', icon: History, label: 'Operations', page: 'chat', render: (o) => `[${o.timestamp.slice(0, 10)}] ${o.action} ${o.entity_type} '${o.entity_name}'` },
  ]

  const hasResults = results && sections.some(s => results[s.key].length > 0)

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[10vh] sm:pt-[15vh]">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-xl mx-2 sm:mx-4 bg-surface0 border border-surface2 rounded-2xl shadow-2xl shadow-black/40 overflow-hidden">
        <div className="flex items-center gap-3 px-4 py-3 border-b border-surface2">
          <Search className="h-4 w-4 text-overlay0 shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search todos, events, conversations, memories..."
            className="flex-1 bg-transparent text-sm text-text placeholder-overlay0 outline-none"
          />
          {loading && <Loader2 className="h-4 w-4 text-overlay0 animate-spin shrink-0" />}
          <button onClick={onClose} className="p-1 rounded-full hover:bg-surface1 text-overlay0 hover:text-text transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>

        {query.trim() && !loading && !hasResults && (
          <div className="px-4 py-8 text-center text-sm text-overlay0">
            No results found for "{query}"
          </div>
        )}

        {hasResults && (
          <div className="max-h-[60vh] overflow-y-auto">
            {sections.map(({ key, icon: Icon, label, page, render }) => {
              const items = results![key]
              if (!items.length) return null
              return (
                <div key={key} className="border-b border-surface1/50 last:border-b-0">
                  <div className="flex items-center gap-2 px-4 py-2 text-xs font-semibold text-overlay1 uppercase tracking-wider">
                    <Icon className="h-3 w-3" />
                    {label} ({items.length})
                  </div>
                  {items.slice(0, 5).map((item: any) => (
                    <button
                      key={item.id}
                      onClick={() => { onNavigate(page); onClose() }}
                      className="w-full text-left px-4 py-2 hover:bg-surface1/50 transition-colors"
                    >
                      <p className="text-sm text-text truncate">{render(item)}</p>
                    </button>
                  ))}
                </div>
              )
            })}
          </div>
        )}

        {!query.trim() && !loading && (
          <div className="px-4 py-8 text-center text-sm text-overlay0">
            Start typing to search across all data
          </div>
        )}
      </div>
    </div>
  )
}
