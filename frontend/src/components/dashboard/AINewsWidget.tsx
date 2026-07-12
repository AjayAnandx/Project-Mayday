import { Newspaper, ExternalLink, Loader2 } from 'lucide-react'
import type { AiNewsResponse } from '../../types/dashboard'

interface AINewsWidgetProps {
  aiNews: AiNewsResponse | null
}

export function AINewsWidget({ aiNews }: AINewsWidgetProps) {
  if (!aiNews) {
    return (
      <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
        <div className="flex items-center gap-2 mb-3">
          <Newspaper className="h-4 w-4 text-green" />
          <h3 className="text-sm font-semibold text-text">AI News</h3>
        </div>
        <div className="flex items-center gap-2 text-xs text-overlay0">
          <Loader2 className="h-3 w-3 animate-spin" />
          Loading...
        </div>
      </div>
    )
  }

  if (aiNews.error) {
    return (
      <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
        <div className="flex items-center gap-2 mb-3">
          <Newspaper className="h-4 w-4 text-green" />
          <h3 className="text-sm font-semibold text-text">AI News</h3>
        </div>
        <p className="text-xs text-overlay0">Unable to fetch AI news</p>
      </div>
    )
  }

  if (aiNews.articles.length === 0) {
    return (
      <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
        <div className="flex items-center gap-2 mb-3">
          <Newspaper className="h-4 w-4 text-green" />
          <h3 className="text-sm font-semibold text-text">AI News</h3>
        </div>
        <p className="text-xs text-overlay0">No articles available</p>
      </div>
    )
  }

  return (
    <div className="rounded-xl bg-surface0/40 border border-surface1/50 p-4 sm:p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Newspaper className="h-4 w-4 text-green" />
          <h3 className="text-sm font-semibold text-text">AI News</h3>
        </div>
        {aiNews.cached_at && (
          <span className="text-[10px] text-overlay0">
            {new Date(aiNews.cached_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>
      <div className="space-y-2">
        {aiNews.articles.map((article, i) => (
          <a
            key={i}
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block p-2.5 rounded-lg hover:bg-surface1/30 transition-colors group"
          >
            <div className="flex items-start gap-2">
              <div className="flex-1 min-w-0">
                <p className="text-sm text-text group-hover:text-green transition-colors leading-snug">
                  {article.title}
                </p>
                {article.summary && (
                  <p className="text-xs text-overlay0 mt-1 line-clamp-2">{article.summary}</p>
                )}
                <div className="flex items-center gap-2 mt-1.5">
                  {article.published_date && (
                    <span className="text-[10px] text-overlay0">{article.published_date}</span>
                  )}
                </div>
              </div>
              <ExternalLink className="h-3 w-3 text-overlay0 shrink-0 mt-1 opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}
