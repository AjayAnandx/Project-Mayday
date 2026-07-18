import { useState, useRef } from 'react'
import { FileText, Upload, X, Search, Trash2, ChevronLeft, Loader2, ExternalLink } from 'lucide-react'
import { useDocuments } from '../../hooks/useDocuments'

import type { DocumentMeta } from '../../types/document'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function DocumentViewer({ doc, onClose }: { doc: DocumentMeta; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-surface0 rounded-2xl w-full max-w-3xl max-h-[85vh] flex flex-col border border-white/10 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <button onClick={onClose} className="text-overlay0 hover:text-text p-1 rounded-lg hover:bg-surface1 transition-colors">
              <ChevronLeft className="h-5 w-5" />
            </button>
            <div className="min-w-0">
              <p className="text-sm font-medium text-text truncate">{doc.filename}</p>
              <p className="text-xs text-overlay0">{doc.pages} pages</p>
            </div>
          </div>
          <button onClick={onClose} className="text-overlay0 hover:text-text p-1 rounded-lg hover:bg-surface1 transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {doc.summary ? (
            <div className="p-4 rounded-xl bg-green/5 border border-green/20">
              <p className="text-xs font-semibold text-green mb-1.5 uppercase tracking-wider">Summary</p>
              <p className="text-sm text-subtext1 leading-relaxed">{doc.summary}</p>
            </div>
          ) : (
            <p className="text-sm text-overlay0 italic">No summary available</p>
          )}
        </div>
      </div>
    </div>
  )
}

export function DocumentPanel() {
  const { documents, loading, search, setSearch, upload, remove, viewText } = useDocuments()
  const [uploading, setUploading] = useState(false)
  const [viewerDoc, setViewerDoc] = useState<DocumentMeta | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().endsWith('.pdf')) return
    setUploading(true)
    try {
      await upload(file)
    } catch {
      // handled by hook
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-crust p-4 sm:p-6">
      <div className="flex items-center justify-between mb-4 shrink-0">
        <h1 className="text-lg font-bold text-text flex items-center gap-2">
          <FileText className="h-5 w-5 text-purple" />
          Documents
        </h1>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleUpload(f)
              e.target.value = ''
            }}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full bg-green/10 text-green hover:bg-green/20 transition-colors disabled:opacity-50"
          >
            {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            <span>{uploading ? 'Uploading...' : 'Upload PDF'}</span>
          </button>
        </div>
      </div>

      <div className="relative mb-4 shrink-0">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-overlay0" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search documents..."
          className="w-full bg-black/60 border border-white/10 rounded-xl pl-9 pr-4 py-2 text-sm text-text placeholder-overlay0 outline-none focus:ring-1 focus:ring-green/50 transition-all"
        />
      </div>

      <div className="flex-1 overflow-y-auto space-y-2">
        {loading && documents.length === 0 ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-5 w-5 text-green animate-spin" />
          </div>
        ) : documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-overlay0">
            <FileText className="h-10 w-10 mb-2 opacity-30" />
            <p className="text-sm">No documents yet</p>
            <p className="text-xs mt-1">Upload a PDF to get started</p>
          </div>
        ) : (
          documents.map((doc) => (
            <div
              key={doc.id}
              className="flex items-center gap-3 bg-surface0/50 rounded-xl px-4 py-3 border border-white/5 hover:border-white/10 transition-colors group"
            >
              <div className="w-9 h-9 rounded-lg bg-purple/10 flex items-center justify-center shrink-0">
                <FileText className="h-4 w-4 text-purple" />
              </div>
              <div
                className="flex-1 min-w-0 cursor-pointer"
                onClick={() => setViewerDoc(doc)}
              >
                <p className="text-sm font-medium text-text truncate">{doc.filename}</p>
                <p className="text-xs text-overlay0">
                  {doc.pages} pages &middot; {formatSize(doc.size)} &middot; {formatDate(doc.uploaded_at)}
                </p>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); setViewerDoc(doc) }}
                className="text-overlay0 hover:text-text p-1.5 rounded-lg hover:bg-surface1 transition-colors opacity-0 group-hover:opacity-100"
                title="View"
              >
                <ExternalLink className="h-4 w-4" />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); remove(doc.id) }}
                className="text-overlay0 hover:text-red p-1.5 rounded-lg hover:bg-red/10 transition-colors opacity-0 group-hover:opacity-100"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))
        )}
      </div>

      <div
        className="shrink-0 mt-4 border-2 border-dashed border-white/10 rounded-xl p-4 text-center text-xs text-overlay0 hover:border-green/30 hover:text-green/70 transition-colors cursor-pointer"
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={async (e) => {
          e.preventDefault()
          const file = e.dataTransfer.files[0]
          if (file) handleUpload(file)
        }}
      >
        <Upload className="h-5 w-5 mx-auto mb-1" />
        Drop a PDF here or click to upload
      </div>

      {viewerDoc && (
        <DocumentViewer
          doc={viewerDoc}
          onClose={() => setViewerDoc(null)}
        />
      )}
    </div>
  )
}
