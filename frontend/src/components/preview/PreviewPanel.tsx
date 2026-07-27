import { useState, useEffect, useRef, useCallback } from 'react'
import { Monitor, RotateCw, ExternalLink, X, Loader2 } from 'lucide-react'
import { cn } from '../../lib/utils'

export function PreviewPanel() {
  const [url, setUrl] = useState('')
  const [iframeUrl, setIframeUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const iframeRef = useRef<HTMLIFrameElement>(null)

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail
      if (typeof detail === 'string') {
        setUrl(detail)
        setIframeUrl(detail)
      }
    }
    window.addEventListener('preview-url', handler)
    return () => window.removeEventListener('preview-url', handler)
  }, [])

  const handleLoad = useCallback(() => {
    setLoading(false)
    setError('')
  }, [])

  const handleError = useCallback(() => {
    setLoading(false)
    setError('Failed to load — is the dev server running?')
  }, [])

  const handleNavigate = () => {
    const trimmed = url.trim()
    if (!trimmed) return
    const finalUrl = /^https?:\/\//i.test(trimmed) ? trimmed : `http://${trimmed}`
    setIframeUrl(finalUrl)
    setLoading(true)
    setError('')
  }

  const handleReload = () => {
    if (!iframeUrl) return
    setLoading(true)
    setError('')
    if (iframeRef.current) {
      iframeRef.current.src = iframeUrl
    }
  }

  return (
    <div className="flex flex-col h-full bg-crust">
      <div className="p-4 pb-2 shrink-0">
        <div className="flex items-center gap-2 sm:gap-3 mb-3 sm:mb-4">
          <div className="w-8 sm:w-10 h-8 sm:h-10 rounded-xl bg-green/15 flex items-center justify-center shrink-0">
            <Monitor className="h-4 sm:h-5 w-4 sm:w-5 text-green" />
          </div>
          <h1 className="text-lg sm:text-xl font-bold text-text">Live Preview</h1>
          {iframeUrl && (
            <span className="text-xs text-overlay1 bg-surface0 px-2 py-0.5 rounded-full truncate max-w-[200px] sm:max-w-[400px]">
              {iframeUrl}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <input
              type="text"
              value={url}
              onChange={e => setUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleNavigate() }}
              placeholder="http://localhost:5174"
              className="w-full bg-mantle border border-surface1 rounded-xl px-4 py-2 pr-10 text-sm text-text placeholder-overlay2 outline-none focus:border-green/50 focus:shadow-[0_0_8px_rgba(34,197,94,0.15)] transition-all"
            />
            {url && (
              <button
                onClick={() => { setUrl(''); setIframeUrl('') }}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-full text-overlay2 hover:text-text hover:bg-surface0 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          <button
            onClick={handleNavigate}
            disabled={!url.trim()}
            className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-green text-crust text-sm font-medium hover:bg-green/90 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <ExternalLink className="h-4 w-4" />
            <span className="hidden sm:inline">Go</span>
          </button>
          {iframeUrl && (
            <button
              onClick={handleReload}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-surface0 text-text text-sm font-medium hover:bg-surface1 transition-all"
            >
              <RotateCw className={cn("h-4 w-4", loading && "animate-spin")} />
              <span className="hidden sm:inline">Reload</span>
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 px-4 pb-4">
        {!iframeUrl ? (
          <div className="h-full rounded-2xl border border-dashed border-surface2 bg-mantle/50 flex flex-col items-center justify-center gap-3 text-overlay1">
            <Monitor className="h-12 w-12 text-overlay0" />
            <p className="text-sm font-medium">Enter a URL to preview</p>
            <p className="text-xs text-overlay2 max-w-sm text-center">
              The LLM will report the dev server URL during the build phase.
              Or paste a URL directly.
            </p>
          </div>
        ) : (
          <div className="h-full rounded-2xl border border-surface1 bg-mantle overflow-hidden relative">
            {loading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-mantle/80">
                <Loader2 className="h-6 w-6 text-green animate-spin" />
              </div>
            )}
            {error && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-mantle/80">
                <div className="text-center">
                  <p className="text-red text-sm font-medium mb-1">Connection Error</p>
                  <p className="text-overlay1 text-xs">{error}</p>
                </div>
              </div>
            )}
            <iframe
              ref={iframeRef}
              src={iframeUrl}
              className="w-full h-full bg-white"
              onLoad={handleLoad}
              onError={handleError}
              title="Live Preview"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            />
          </div>
        )}
      </div>
    </div>
  )
}
