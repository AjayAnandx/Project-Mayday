import { useState, useRef, useCallback, useEffect } from 'react'
import { Upload, FileSpreadsheet, Trash2, Eye, ChevronLeft, Loader2, Database, X, Plus } from 'lucide-react'
import { api } from '../../services/api'
import type { DataImportFile, DataImportParseResult } from '../../types/data-import'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

interface ParsedFileViewerProps {
  result: DataImportParseResult
  onClose: () => void
  onImport: (storeType: 'research' | 'project', options?: { topic?: string; projectName?: string }) => void
}

function ParsedFileViewer({ result, onClose, onImport }: ParsedFileViewerProps) {
  const [importing, setImporting] = useState<'research' | 'project' | null>(null)
  const [topicInput, setTopicInput] = useState('')
  const [projectInput, setProjectInput] = useState('')
  const [error, setError] = useState('')

  const handleImport = async (storeType: 'research' | 'project') => {
    setImporting(storeType)
    setError('')
    try {
      if (storeType === 'research' && !topicInput.trim()) {
        setError('Topic name is required for research import')
        setImporting(null)
        return
      }
      if (storeType === 'project' && !projectInput.trim()) {
        setError('Project name is required for project import')
        setImporting(null)
        return
      }

      await api.importDataToStore(result.file_id, storeType, {
        topic: storeType === 'research' ? topicInput.trim() : undefined,
        projectName: storeType === 'project' ? projectInput.trim() : undefined,
      })
      onClose()
    } catch (err: any) {
      setError(err.message || 'Import failed')
    } finally {
      setImporting(null)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-surface0 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col border border-white/10 shadow-2xl overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <button onClick={onClose} className="text-overlay0 hover:text-text p-1 rounded-lg hover:bg-surface1 transition-colors">
              <ChevronLeft className="h-5 w-5" />
            </button>
            <div className="min-w-0">
              <p className="text-sm font-medium text-text truncate">Parsed Data Preview</p>
              <p className="text-xs text-overlay0">{result.row_count} rows · {result.columns.length} columns</p>
            </div>
          </div>
          <button onClick={onClose} className="text-overlay0 hover:text-text p-1 rounded-lg hover:bg-surface1 transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div className="grid grid-cols-3 gap-3 text-sm">
            <div className="p-3 rounded-xl bg-green/5 border border-green/20">
              <p className="text-xs font-semibold text-green mb-1 uppercase tracking-wider">Rows</p>
              <p className="text-lg font-bold text-text">{result.row_count}</p>
            </div>
            <div className="p-3 rounded-xl bg-blue/5 border border-blue/20">
              <p className="text-xs font-semibold text-blue mb-1 uppercase tracking-wider">Columns</p>
              <p className="text-lg font-bold text-text">{result.columns.length}</p>
            </div>
            <div className="p-3 rounded-xl bg-purple/5 border border-purple/20">
              <p className="text-xs font-semibold text-purple mb-1 uppercase tracking-wider">Numeric Cols</p>
              <p className="text-lg font-bold text-text">{result.detected.numeric_cols.length}</p>
            </div>
          </div>

          <div className="space-y-3">
            <h4 className="text-sm font-medium text-text">Column Types</h4>
            <div className="flex flex-wrap gap-2">
              {result.detected.date_cols.map((col) => (
                <span key={col} className="px-2 py-1 text-xs rounded-full bg-blue/10 text-blue border border-blue/20">{col} (date)</span>
              ))}
              {result.detected.numeric_cols.map((col) => (
                <span key={col} className="px-2 py-1 text-xs rounded-full bg-green/10 text-green border border-green/20">{col} (numeric)</span>
              ))}
              {result.detected.categorical_cols.map((col) => (
                <span key={col} className="px-2 py-1 text-xs rounded-full bg-purple/10 text-purple border border-purple/20">{col} (categorical)</span>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            <h4 className="text-sm font-medium text-text">Sample Data (first 10 rows)</h4>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-left text-overlay0 border-b border-white/10">
                    {result.columns.map((col) => (
                      <th key={col} className="px-3 py-2 font-medium">{col}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.sample.map((row, rowIdx) => (
                    <tr key={rowIdx} className="border-b border-white/5 hover:bg-white/5">
                      {result.columns.map((col) => (
                        <td key={col} className="px-3 py-2 text-subtext1">{row[col] ?? ''}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {error && (
            <div className="p-3 rounded-xl bg-red/10 border border-red/20 text-red text-sm">{error}</div>
          )}

          <div className="pt-4 border-t border-white/10">
            <h4 className="text-sm font-medium text-text mb-3">Import to Store</h4>
            <div className="grid grid-cols-2 gap-3">
              <div className="p-4 rounded-xl border border-white/10 bg-surface1/50">
                <div className="flex items-center gap-2 mb-3">
                  <Database className="h-4 w-4 text-purple" />
                  <span className="font-medium text-text">Research</span>
                </div>
                <input
                  type="text"
                  value={topicInput}
                  onChange={(e) => setTopicInput(e.target.value)}
                  placeholder="Research topic name"
                  className="w-full bg-black/60 border border-white/10 rounded-xl px-3 py-2 text-sm text-text placeholder-overlay0 outline-none focus:ring-1 focus:ring-green/50 transition-all mb-3"
                />
                <button
                  onClick={() => handleImport('research')}
                  disabled={importing === 'research'}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-full bg-purple/10 text-purple hover:bg-purple/20 transition-colors disabled:opacity-50 text-sm font-medium"
                >
                  {importing === 'research' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  <span>{importing === 'research' ? 'Importing...' : 'Import Data Points'}</span>
                </button>
              </div>
              <div className="p-4 rounded-xl border border-white/10 bg-surface1/50">
                <div className="flex items-center gap-2 mb-3">
                  <Database className="h-4 w-4 text-amber" />
                  <span className="font-medium text-text">Project</span>
                </div>
                <input
                  type="text"
                  value={projectInput}
                  onChange={(e) => setProjectInput(e.target.value)}
                  placeholder="Project name"
                  className="w-full bg-black/60 border border-white/10 rounded-xl px-3 py-2 text-sm text-text placeholder-overlay0 outline-none focus:ring-1 focus:ring-green/50 transition-all mb-3"
                />
                <button
                  onClick={() => handleImport('project')}
                  disabled={importing === 'project'}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-full bg-amber/10 text-amber hover:bg-amber/20 transition-colors disabled:opacity-50 text-sm font-medium"
                >
                  {importing === 'project' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                  <span>{importing === 'project' ? 'Importing...' : 'Import Data Points'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export function DataImportPanel() {
  const [files, setFiles] = useState<DataImportFile[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [parsing, setParsing] = useState<string | null>(null)
  const [parsedResult, setParsedResult] = useState<DataImportParseResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadFiles = useCallback(async () => {
    try {
      const data = await api.listDataFiles()
      setFiles(data.files || [])
    } catch {
      setFiles([])
    } finally {
      setLoading(false)
    }
  }, [])

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().match(/\.(xlsx|xls|csv)$/)) return
    setUploading(true)
    try {
      await api.uploadDataFile(file)
      await loadFiles()
    } catch (err: any) {
      alert(err.message || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const handleParse = async (fileId: string) => {
    setParsing(fileId)
    try {
      const result = await api.parseDataFile(fileId)
      setParsedResult(result)
    } catch (err: any) {
      alert(err.message || 'Parse failed')
    } finally {
      setParsing(null)
    }
  }

  const handleDelete = async (fileId: string) => {
    // Note: Backend doesn't have delete endpoint yet
    alert('Delete not implemented yet')
  }

  // Load files on mount
  useEffect(() => {
    loadFiles()
  }, [loadFiles])

  return (
    <div className="flex flex-col h-full bg-crust p-4 sm:p-6">
      <div className="flex items-center justify-between mb-4 shrink-0">
        <h1 className="text-lg font-bold text-text flex items-center gap-2">
          <FileSpreadsheet className="h-5 w-5 text-green" />
          Data Import
        </h1>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls,.csv"
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
            <span>{uploading ? 'Uploading...' : 'Upload File'}</span>
          </button>
        </div>
      </div>

      <div
        className="shrink-0 mb-4 border-2 border-dashed border-white/10 rounded-xl p-4 text-center text-xs text-overlay0 hover:border-green/30 hover:text-green/70 transition-colors cursor-pointer"
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={async (e) => {
          e.preventDefault()
          const file = e.dataTransfer.files[0]
          if (file) handleUpload(file)
        }}
      >
        <Upload className="h-6 w-6 mx-auto mb-2" />
        <p>Drop an Excel or CSV file here or click to upload</p>
        <p className="mt-1 text-xs">Supports .xlsx, .xls, .csv</p>
      </div>

      <div className="flex-1 overflow-y-auto space-y-2">
        {loading && files.length === 0 ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-5 w-5 text-green animate-spin" />
          </div>
        ) : files.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-overlay0">
            <FileSpreadsheet className="h-10 w-10 mb-2 opacity-30" />
            <p className="text-sm">No files uploaded yet</p>
            <p className="text-xs mt-1">Upload an Excel or CSV file to get started</p>
          </div>
        ) : (
          files.map((file) => (
            <div
              key={file.file_id}
              className="flex items-center gap-3 bg-surface0/50 rounded-xl px-4 py-3 border border-white/5 hover:border-white/10 transition-colors group"
            >
              <div className="w-9 h-9 rounded-lg bg-green/10 flex items-center justify-center shrink-0">
                <FileSpreadsheet className="h-4 w-4 text-green" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text truncate">{file.name}</p>
                <p className="text-xs text-overlay0">
                  {formatSize(file.size)} &middot; {formatDate(file.modified)}
                </p>
              </div>
              <button
                onClick={() => handleParse(file.file_id)}
                disabled={parsing === file.file_id}
                className="text-overlay0 hover:text-text p-1.5 rounded-lg hover:bg-surface1 transition-colors opacity-0 group-hover:opacity-100"
                title="Parse & Preview"
              >
                {parsing === file.file_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />}
              </button>
              <button
                onClick={() => handleDelete(file.file_id)}
                className="text-overlay0 hover:text-red p-1.5 rounded-lg hover:bg-red/10 transition-colors opacity-0 group-hover:opacity-100"
                title="Delete"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))
        )}
      </div>

      {parsedResult && (
        <ParsedFileViewer
          result={parsedResult}
          onClose={() => setParsedResult(null)}
          onImport={(storeType, options) => {
            // handled in ParsedFileViewer
          }}
        />
      )}
    </div>
  )
}