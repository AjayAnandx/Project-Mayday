import { useState, useCallback } from 'react'
import { X, ExternalLink, RefreshCw, AlertTriangle } from 'lucide-react'

interface ArtifactPanelProps {
  url: string | null
  title: string
  onClose: () => void
}

export function ArtifactPanel({ url, title, onClose }: ArtifactPanelProps) {
  const [error, setError] = useState(false)
  const [key, setKey] = useState(0)

  const handleError = useCallback(() => {
    setError(true)
  }, [])

  const handleRetry = useCallback(() => {
    setError(false)
    setKey((k) => k + 1)
  }, [])

  if (!url) return null

  const fullUrl = url.startsWith('http') ? url : url

  return (
    <div className="w-full h-full flex flex-col bg-surface0 border-l border-surface2">
      <div className="flex items-center justify-between px-4 py-2 bg-surface1 border-b border-surface2 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-accent text-sm font-medium truncate">{title}</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleRetry}
            className="p-1.5 rounded-lg hover:bg-surface2 text-overlay1 hover:text-text transition-colors"
            title="Reload"
          >
            <RefreshCw size={14} />
          </button>
          <a
            href={fullUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1.5 rounded-lg hover:bg-surface2 text-overlay1 hover:text-text transition-colors"
            title="Open in new tab"
          >
            <ExternalLink size={14} />
          </a>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-surface2 text-overlay1 hover:text-text transition-colors"
            title="Close"
          >
            <X size={14} />
          </button>
        </div>
      </div>
      <div className="flex-1 relative">
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-10">
            <div className="text-center px-6">
              <AlertTriangle size={32} className="text-yellow-500 mx-auto mb-2" />
              <p className="text-text mb-3">Failed to load preview</p>
              <button
                onClick={handleRetry}
                className="px-4 py-1.5 bg-accent text-black rounded-full text-sm font-medium hover:bg-green-400 transition-colors"
              >
                Retry
              </button>
            </div>
          </div>
        )}
        <iframe
          key={key}
          src={fullUrl}
          className="w-full h-full border-none"
          sandbox="allow-scripts allow-same-origin"
          title={title}
          onError={handleError}
        />
      </div>
    </div>
  )
}
