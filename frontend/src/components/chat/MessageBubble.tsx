import { useState } from 'react'
import { Check, ChevronDown, Copy, ExternalLink, Wrench } from 'lucide-react'
import type { ChatMessage } from '../../hooks/useChat'
import { cn } from '../../lib/utils'
import { MarkdownRenderer } from './MarkdownRenderer'
import { ChatOpenUIBlock } from '../../openui/ChatOpenUIBlock'

/** Small gradient "M" mark used as Mayday's avatar. */
export function MaydayAvatar({ size = 'md', pulse = false }: { size?: 'sm' | 'md'; pulse?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        'shrink-0 rounded-[10px] bg-gradient-to-br from-[#4ade80] to-[#15803d] flex items-center justify-center text-black font-bold shadow-[0_0_14px_rgba(34,197,94,0.3)]',
        size === 'sm' ? 'w-6 h-6 text-[10px] rounded-lg' : 'w-8 h-8 text-xs',
        pulse && 'animate-pulse',
      )}
    >
      M
    </span>
  )
}

const TOOL_FAMILIES: [prefix: string, label: string][] = [
  ['plan_', 'Planner'], ['gmail_', 'Gmail'], ['maps_', 'Maps'], ['music_', 'Music'], ['video_', 'Video'],
  ['opencode_', 'Code'], ['git_', 'Git'], ['sandbox_', 'Sandbox'], ['playwright_', 'Browser'],
  ['research', 'Research'], ['web_search', 'Web search'], ['web_fetch', 'Web'], ['recall', 'Memory'],
  ['remember', 'Memory'], ['forget', 'Memory'], ['delete_entity', 'Memory'], ['add_project', 'Projects'],
  ['create_project', 'Projects'], ['list_project', 'Projects'], ['update_task', 'Projects'],
]

/** "plan_add" → "Planner · add", "web_search_exa" → "Web search". */
export function prettyToolName(name = '') {
  const fam = TOOL_FAMILIES.find(([p]) => name.startsWith(p))
  if (fam) {
    const rest = name.slice(fam[0].length).replace(/^_/, '').replace(/_?exa$/, '').replace(/_/g, ' ').trim()
    return rest ? `${fam[1]} · ${rest}` : fam[1]
  }
  const s = name.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text)
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        } catch { /* clipboard blocked */ }
      }}
      aria-label={copied ? 'Copied' : 'Copy message'}
      className="flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-overlay1 hover:text-text hover:bg-white/5"
    >
      {copied ? <Check className="h-3 w-3 text-green" /> : <Copy className="h-3 w-3" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

/** A run of consecutive tool calls, collapsed into one card. */
export function ToolActivity({ tools, compact = false }: { tools: ChatMessage[]; compact?: boolean }) {
  const media = tools.filter(t => t.image_url || (t.artifact_url && t.artifact_title))
  const cards = tools.filter(t => t.ui?.lang)
  const [open, setOpen] = useState(false)
  // An approval card alone needs no "used a tool" header.
  if (tools.length === 1 && tools[0].tool_name === 'approval' && tools[0].ui) {
    return (
      <div className={cn(compact ? 'pl-0' : 'pl-11')}><ChatOpenUIBlock ui={tools[0].ui} expandable={false} /></div>
    )
  }
  const names = [...new Set(tools.map(t => prettyToolName(t.tool_name).split(' · ')[0]))]

  return (
    <div className={cn('flex gap-3', compact ? 'pl-0' : 'pl-11')}>
      <div className="min-w-0 flex-1 rounded-2xl border border-white/[0.06] bg-white/[0.02]">
        <button
          onClick={() => setOpen(o => !o)}
          aria-expanded={open}
          className="w-full flex items-center gap-2 px-3 py-2 text-left"
        >
          <span className="w-5 h-5 rounded-md bg-green/15 flex items-center justify-center shrink-0">
            <Wrench className="h-3 w-3 text-green" />
          </span>
          <span className="text-xs text-subtext0 truncate flex-1">
            {tools.length === 1
              ? <><span className="text-subtext1">{prettyToolName(tools[0].tool_name)}</span><span className="text-overlay1"> — {tools[0].content.split('\n')[0].slice(0, 90)}</span></>
              : <>Used <span className="text-subtext1">{tools.length} tools</span> · {names.slice(0, 4).join(', ')}{names.length > 4 ? '…' : ''}</>}
          </span>
          <ChevronDown className={cn('h-3.5 w-3.5 text-overlay1 shrink-0 transition-transform', open && 'rotate-180')} />
        </button>
        {open && (
          <ol className="border-t border-white/[0.05] px-3 py-2 space-y-2">
            {tools.map(t => (
              <li key={t.id} className="text-[11px]">
                <p className="font-medium text-green/90">{prettyToolName(t.tool_name)}</p>
                <pre className="mt-0.5 whitespace-pre-wrap break-words font-mono text-[10.5px] leading-relaxed text-overlay2 max-h-40 overflow-y-auto">{t.content}</pre>
              </li>
            ))}
          </ol>
        )}
        {cards.map(t => (
          <div key={`ui-${t.id}`} className="border-t border-white/[0.05] p-3">
            <ChatOpenUIBlock ui={t.ui!} />
          </div>
        ))}
        {media.map(t => (
          <div key={`m-${t.id}`} className="border-t border-white/[0.05] p-2">
            {t.image_url && (
              <img src={t.image_url} alt={`Result of ${prettyToolName(t.tool_name)}`}
                   className="max-h-72 w-full object-contain rounded-xl bg-black/40" />
            )}
            {t.artifact_url && t.artifact_title && (
              <button onClick={() => window.open(t.artifact_url!, '_blank')}
                      className="mt-1 flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-green hover:bg-green/10">
                <ExternalLink className="h-3 w-3" /> {t.ui ? 'Open full page' : <>Open “{t.artifact_title}”</>}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

interface MessageBubbleProps {
  message: ChatMessage
  /** tighter layout for side panels (voice transcript) */
  compact?: boolean
}

export function MessageBubble({ message, compact = false }: MessageBubbleProps) {
  if (message.role === 'tool') return <ToolActivity tools={[message]} compact={compact} />
  if (message.role === 'assistant' && !message.content) return null

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className={cn(
          'rounded-2xl rounded-br-md bg-white/[0.07] border border-white/[0.06] text-text whitespace-pre-wrap break-words',
          compact ? 'max-w-[90%] px-3 py-2 text-xs' : 'max-w-[80%] px-4 py-2.5 text-sm',
        )}>
          {message.content}
        </div>
      </div>
    )
  }

  if (message.content.startsWith('Error:')) {
    return (
      <div className="flex gap-3" role="alert">
        {!compact && <MaydayAvatar />}
        <div className={cn('min-w-0 flex-1 rounded-2xl border border-red/25 bg-red/[0.06] text-red/90',
          compact ? 'px-3 py-2 text-xs' : 'px-4 py-3 text-sm')}>
          <p className="font-medium text-red">Something went wrong</p>
          <p className="mt-1 text-subtext0 break-words">{message.content.replace(/^Error:\s*/, '')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="group flex gap-3">
      {!compact && <MaydayAvatar />}
      <div className="min-w-0 flex-1">
        <div className={cn('text-text', compact ? 'text-xs' : 'text-sm pt-1')}>
          <MarkdownRenderer content={message.content} />
        </div>
        {!compact && (
          <div className="mt-1 -ml-1.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
            <CopyButton text={message.content} />
          </div>
        )}
      </div>
    </div>
  )
}
