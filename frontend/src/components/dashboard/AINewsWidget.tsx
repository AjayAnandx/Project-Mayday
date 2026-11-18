import { Newspaper, ArrowUpRight, Loader2 } from 'lucide-react'
import type { AiNewsResponse } from '../../types/dashboard'
import { DashCard, CardHeader } from './DashCard'

function domain(url: string) {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return '' }
}

/** Exa returns page title + "| Site" suffix; keep the headline only. */
function headline(title: string) {
  return title.split(' | ')[0].trim()
}

export function AINewsWidget({ aiNews, className }: { aiNews: AiNewsResponse | null; className?: string }) {
  const updated = aiNews?.cached_at
    ? new Date(aiNews.cached_at).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
    : null

  let body: React.ReactNode
  if (!aiNews) {
    body = (
      <div className="flex items-center gap-2 text-xs text-overlay1 py-6 justify-center">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading headlines…
      </div>
    )
  } else if (aiNews.error || aiNews.articles.length === 0) {
    body = (
      <div className="flex-1 rounded-2xl bg-hatch border border-white/[0.04] flex items-center justify-center py-8 px-4 text-center">
        <p className="text-xs text-overlay1">{aiNews.error ? 'Unable to fetch AI news right now' : 'No articles available'}</p>
      </div>
    )
  } else {
    body = (
      <ol className="divide-y divide-white/[0.05] -my-1">
        {aiNews.articles.map((a, i) => (
          <li key={a.url}>
            <a
              href={a.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group flex gap-3 py-2.5"
            >
              <span className="text-[11px] font-mono text-overlay0 pt-0.5 tabular-nums">{String(i + 1).padStart(2, '0')}</span>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] leading-snug text-text line-clamp-2 group-hover:text-green transition-colors">
                  {headline(a.title)}
                </p>
                <p className="text-[10px] text-overlay1 mt-1">
                  {domain(a.url)}{a.published_date ? ` · ${a.published_date}` : ''}
                </p>
              </div>
              <ArrowUpRight className="h-3.5 w-3.5 text-overlay0 group-hover:text-green shrink-0 mt-0.5 transition-colors" />
            </a>
          </li>
        ))}
      </ol>
    )
  }

  return (
    <DashCard className={className}>
      <CardHeader
        title="AI News"
        icon={Newspaper}
        right={updated && <span className="text-[11px] text-overlay1">updated {updated}</span>}
      />
      {body}
    </DashCard>
  )
}
