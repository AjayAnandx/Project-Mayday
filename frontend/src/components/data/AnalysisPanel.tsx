import { useState, useRef, useCallback, useEffect } from 'react'
import {
  Upload, FileSpreadsheet, Eye, ChevronLeft, Loader2,
  Database, X, Plus, BarChart3, Globe, Table2, Send, ExternalLink,
} from 'lucide-react'
import { api } from '../../services/api'
import { useChatContext } from '../../context/ChatContext'
import { useDataAnalysis } from '../../hooks/useDataAnalysis'
import type { DataImportFile, DataImportParseResult, ChartOutput } from '../../types/data-import'
import type { Project } from '../../types/project'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

type Tab = 'import' | 'web' | 'points' | 'charts'

/* ── Tab 1: Excel/CSV Import ─────────────────────────────────── */

function ImportTab() {
  const [files, setFiles] = useState<DataImportFile[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [parsing, setParsing] = useState<string | null>(null)
  const [parsed, setParsed] = useState<DataImportParseResult | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [storeType, setStoreType] = useState<'research' | 'project'>('research')
  const [topicInput, setTopicInput] = useState('')
  const [projectId, setProjectId] = useState('')
  const [projects, setProjects] = useState<Project[]>([])
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState('')
  const [importResult, setImportResult] = useState<{ message: string; data_points: number } | null>(null)
  const [generatingChart, setGeneratingChart] = useState(false)

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

  useEffect(() => {
    loadFiles()
  }, [loadFiles])

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]))
  }, [])

  const handleUpload = async (file: File) => {
    if (!file.name.toLowerCase().match(/\.(xlsx|xls|csv)$/)) return
    setUploading(true)
    try {
      await api.uploadDataFile(file)
      await loadFiles()
    } catch {
      // handled by api error
    } finally {
      setUploading(false)
    }
  }

  const handleParse = async (fileId: string) => {
    setParsing(fileId)
    try {
      const result = await api.parseDataFile(fileId)
      setParsed(result)
      setImportResult(null)
      setImportError('')
    } catch {
      // handled by api error
    } finally {
      setParsing(null)
    }
  }

  const handleImport = async () => {
    if (!parsed) return
    setImporting(true)
    setImportError('')
    setImportResult(null)
    try {
      if (storeType === 'research') {
        if (!topicInput.trim()) throw new Error('Enter a topic name for the research record')
        try {
          const result = await api.importDataToStore(parsed.file_id, 'research', { topic: topicInput.trim() })
          setImportResult({ message: result.message, data_points: result.data_points })
        } catch (err: any) {
          if (!String(err.message || '').toLowerCase().includes('not found')) throw err
          await api.createResearch({ topic: topicInput.trim(), type: 'market' })
          const result = await api.importDataToStore(parsed.file_id, 'research', { topic: topicInput.trim() })
          setImportResult({ message: result.message, data_points: result.data_points })
        }
      } else {
        if (!projectId) throw new Error('Select a project to import into')
        const result = await api.importDataToStore(parsed.file_id, 'project', { projectName: projectId })
        setImportResult({ message: result.message, data_points: result.data_points })
      }
    } catch (err: any) {
      setImportError(err.message || 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  const handleGenerateAfterImport = async () => {
    if (!importResult) return
    setGeneratingChart(true)
    setImportError('')
    try {
      const res = storeType === 'research' && topicInput.trim()
        ? await api.generateResearchChart({ topic: topicInput.trim(), chart_type: 'auto' })
        : await api.generateProjectChart(projectId, { chart_type: 'auto' })
      const url = res.relative_url || res.url
      if (url) window.open(url, '_blank')
    } catch (err: any) {
      setImportError(err.message || 'Chart generation failed — add data first')
    } finally {
      setGeneratingChart(false)
    }
  }

  return (
    <div className="flex flex-col h-full gap-4">
      <div
        className="shrink-0 border-2 border-dashed border-white/10 rounded-xl p-4 text-center text-xs text-overlay0 hover:border-green/30 hover:text-green/70 transition-colors cursor-pointer"
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={async (e) => {
          e.preventDefault()
          const file = e.dataTransfer.files[0]
          if (file) handleUpload(file)
        }}
      >
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
          </div>
        ) : (
          files.map((file) => (
            <div key={file.file_id} className="flex items-center gap-3 bg-surface0/50 rounded-xl px-4 py-3 border border-white/5 hover:border-white/10 transition-colors group">
              <div className="w-9 h-9 rounded-lg bg-green/10 flex items-center justify-center shrink-0">
                <FileSpreadsheet className="h-4 w-4 text-green" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text truncate">{file.name}</p>
                <p className="text-xs text-overlay0">{formatSize(file.size)}</p>
              </div>
              <button
                onClick={() => handleParse(file.file_id)}
                disabled={parsing === file.file_id}
                className="text-overlay0 hover:text-text p-1.5 rounded-lg hover:bg-surface1 transition-colors opacity-0 group-hover:opacity-100"
                title="Parse & Preview"
              >
                {parsing === file.file_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          ))
        )}
      </div>

      {parsed && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-surface0 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col border border-white/10 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 shrink-0">
              <div className="flex items-center gap-3 min-w-0">
                <button onClick={() => setParsed(null)} className="text-overlay0 hover:text-text p-1 rounded-lg hover:bg-surface1 transition-colors">
                  <ChevronLeft className="h-5 w-5" />
                </button>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text truncate">Parsed Data Preview</p>
                  <p className="text-xs text-overlay0">{parsed.row_count} rows · {parsed.columns.length} columns</p>
                </div>
              </div>
              <button onClick={() => setParsed(null)} className="text-overlay0 hover:text-text p-1 rounded-lg hover:bg-surface1 transition-colors">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              <div className="grid grid-cols-3 gap-3 text-sm">
                <div className="p-3 rounded-xl bg-green/5 border border-green/20">
                  <p className="text-xs font-semibold text-green mb-1 uppercase tracking-wider">Rows</p>
                  <p className="text-lg font-bold text-text">{parsed.row_count}</p>
                </div>
                <div className="p-3 rounded-xl bg-blue/5 border border-blue/20">
                  <p className="text-xs font-semibold text-blue mb-1 uppercase tracking-wider">Columns</p>
                  <p className="text-lg font-bold text-text">{parsed.columns.length}</p>
                </div>
                <div className="p-3 rounded-xl bg-purple/5 border border-purple/20">
                  <p className="text-xs font-semibold text-purple mb-1 uppercase tracking-wider">Numeric Cols</p>
                  <p className="text-lg font-bold text-text">{parsed.detected.numeric_cols.length}</p>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="text-left text-overlay0 border-b border-white/10">
                      {parsed.columns.map((col) => <th key={col} className="px-3 py-2 font-medium">{col}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {parsed.sample.map((row, idx) => (
                      <tr key={idx} className="border-b border-white/5 hover:bg-white/5">
                        {parsed.columns.map((col) => <td key={col} className="px-3 py-2 text-subtext1">{row[col] ?? ''}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-overlay0">
                Tip: ask the assistant in Chat to "analyze {parsed.file_id}" — it can import this file into research or a project and auto-generate a chart.
              </p>
            </div>
            <div className="shrink-0 border-t border-white/5 px-5 py-4 space-y-3">
              <p className="text-xs font-medium text-text uppercase tracking-wider flex items-center gap-1.5">
                <Database className="h-3.5 w-3.5 text-green" />
                Import to store
              </p>
              <div className="flex items-center gap-2 flex-wrap">
                <div className="flex items-center gap-1 bg-black/60 border border-white/10 rounded-full px-1.5 py-1">
                  <button
                    onClick={() => { setStoreType('research'); setImportResult(null); }}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${storeType === 'research' ? 'bg-purple/10 text-purple' : 'text-overlay0 hover:text-text hover:bg-white/5'}`}
                  >
                    Research
                  </button>
                  <button
                    onClick={() => { setStoreType('project'); setImportResult(null); }}
                    className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${storeType === 'project' ? 'bg-amber/10 text-amber' : 'text-overlay0 hover:text-text hover:bg-white/5'}`}
                  >
                    Project
                  </button>
                </div>
                {storeType === 'research' ? (
                  <input
                    value={topicInput}
                    onChange={(e) => setTopicInput(e.target.value)}
                    placeholder="Topic name (e.g. Engineering Growth)"
                    className="flex-1 min-w-[180px] bg-black/60 border border-white/10 rounded-xl px-3 py-1.5 text-sm text-text placeholder-overlay0 outline-none focus:ring-1 focus:ring-green/50"
                  />
                ) : (
                  <select
                    value={projectId}
                    onChange={(e) => { setProjectId(e.target.value); setImportResult(null); }}
                    className="flex-1 min-w-[180px] bg-black/60 border border-white/10 rounded-xl px-3 py-1.5 text-sm text-text outline-none focus:ring-1 focus:ring-green/50"
                  >
                    <option value="">Select project…</option>
                    {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                )}
                <button
                  onClick={handleImport}
                  disabled={importing || (storeType === 'research' ? !topicInput.trim() : !projectId)}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-green/10 text-green hover:bg-green/20 transition-colors disabled:opacity-50 text-sm font-medium"
                >
                  {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />}
                  {importing ? 'Importing…' : 'Import'}
                </button>
              </div>
              {importError && <p className="text-xs text-red">{importError}</p>}
              {importResult && (
                <div className="flex items-center justify-between gap-3 bg-green/5 border border-green/20 rounded-xl px-4 py-3">
                  <div className="min-w-0">
                    <p className="text-sm text-text font-medium">{importResult.message}</p>
                    <p className="text-xs text-overlay0">stored data points are now chartable</p>
                  </div>
                  <button
                    onClick={handleGenerateAfterImport}
                    disabled={generatingChart}
                    className="flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-green/10 text-green hover:bg-green/20 transition-colors disabled:opacity-50 text-sm font-medium shrink-0"
                  >
                    {generatingChart ? <Loader2 className="h-4 w-4 animate-spin" /> : <BarChart3 className="h-4 w-4" />}
                    {generatingChart ? 'Generating…' : 'Generate Chart'}
                  </button>
                </div>
              )}
              <p className="text-xs text-overlay0">
                Research records are auto-created if the topic doesn't exist. Charts open in a new tab.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Tab 2: Web Research ─────────────────────────────────────── */

function WebResearchTab() {
  const { sendMessage, connected } = useChatContext()
  const [query, setQuery] = useState('')
  const [sent, setSent] = useState(false)

  const handleSend = () => {
    if (!query.trim()) return
    sendMessage(query.trim())
    setSent(true)
    setQuery('')
  }

  return (
    <div className="flex flex-col h-full gap-4">
      <div className="shrink-0 bg-surface0/50 rounded-xl p-4 border border-white/5">
        <h3 className="text-sm font-medium text-text flex items-center gap-2 mb-1">
          <Globe className="h-4 w-4 text-green" />
          Web → Structured Data
        </h3>
        <p className="text-xs text-overlay0 mb-3">
          Ask in natural language. The assistant searches the web (Exa), extracts structured rows,
          stores them as data points, and auto-generates a chart that opens in a new tab.
        </p>
        <div className="flex items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            placeholder='e.g. "ML Engineer vs Full Stack Engineer job growth 2015-2024"'
            className="flex-1 bg-black/60 border border-white/10 rounded-xl px-4 py-2 text-sm text-text placeholder-overlay0 outline-none focus:ring-1 focus:ring-green/50 transition-all"
          />
          <button
            onClick={handleSend}
            disabled={!query.trim() || !connected}
            className="flex items-center gap-1.5 px-3 py-2 rounded-full bg-green/10 text-green hover:bg-green/20 transition-colors disabled:opacity-50 text-sm font-medium shrink-0"
          >
            <Send className="h-4 w-4" />
            Run Analysis
          </button>
        </div>
        {!connected && <p className="text-xs text-red mt-2">Not connected — start the backend to run analyses.</p>}
      </div>

      {sent && (
        <div className="flex-1 flex flex-col items-center justify-center text-center text-overlay0">
          <Globe className="h-10 w-10 mb-2 opacity-30" />
          <p className="text-sm max-w-md">
            Analysis dispatched to the assistant in the <span className="text-green">Chat</span> tab.
            Watch the tool calls — when the chart is generated it will open automatically.
          </p>
        </div>
      )}
    </div>
  )
}

/* ── Tab 3: Data Points ──────────────────────────────────────── */

function DataPointsTab() {
  const {
    researchList, projectList, loading, activeResearch, activeProject,
    selectResearch, selectProject, addResearchPoint, addProjectPoint,
  } = useDataAnalysis()
  const [mode, setMode] = useState<'research' | 'project'>('research')
  const [label, setLabel] = useState('')
  const [value, setValue] = useState('')
  const [unit, setUnit] = useState('')
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState('')

  const active = mode === 'research' ? activeResearch : activeProject

  const handleAdd = async () => {
    if (!active || !label.trim() || !value.trim()) return
    setAdding(true)
    setError('')
    try {
      if (mode === 'research' && activeResearch) {
        await addResearchPoint(activeResearch.topic, label.trim(), value.trim(), unit.trim() || undefined)
      } else if (activeProject) {
        await addProjectPoint(activeProject.id, label.trim(), value.trim(), unit.trim() || undefined)
      }
      setLabel('')
      setValue('')
      setUnit('')
    } catch (err: any) {
      setError(err.message || 'Failed to add data point')
    } finally {
      setAdding(false)
    }
  }

  const points = active?.data_points ?? []

  return (
    <div className="flex flex-col h-full gap-4">
      <div className="shrink-0 flex items-center gap-2">
        <button
          onClick={() => setMode('research')}
          className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${mode === 'research' ? 'bg-purple/10 text-purple' : 'text-overlay0 hover:text-text hover:bg-white/5'}`}
        >
          Research
        </button>
        <button
          onClick={() => setMode('project')}
          className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${mode === 'project' ? 'bg-amber/10 text-amber' : 'text-overlay0 hover:text-text hover:bg-white/5'}`}
        >
          Project
        </button>
        <div className="flex-1" />
        <select
          value={mode === 'research' ? (activeResearch?.topic ?? '') : (activeProject?.id ?? '')}
          onChange={(e) => mode === 'research' ? selectResearch(e.target.value) : selectProject(e.target.value)}
          className="bg-black/60 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-text outline-none focus:ring-1 focus:ring-green/50 max-w-[220px]"
        >
          <option value="">Select {mode}…</option>
          {mode === 'research'
            ? researchList.map((r) => <option key={r.id} value={r.topic}>{r.topic}</option>)
            : projectList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>

      {active && (
        <div className="shrink-0 bg-surface0/50 rounded-xl p-3 border border-white/5 flex items-center gap-2">
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Label (e.g. 2020 / ML Engineer)"
            className="flex-1 min-w-0 bg-black/60 border border-white/10 rounded-xl px-3 py-1.5 text-sm text-text placeholder-overlay0 outline-none focus:ring-1 focus:ring-green/50"
          />
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Value"
            className="w-24 bg-black/60 border border-white/10 rounded-xl px-3 py-1.5 text-sm text-text placeholder-overlay0 outline-none focus:ring-1 focus:ring-green/50"
          />
          <input
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder="Unit"
            className="w-20 bg-black/60 border border-white/10 rounded-xl px-3 py-1.5 text-sm text-text placeholder-overlay0 outline-none focus:ring-1 focus:ring-green/50"
          />
          <button
            onClick={handleAdd}
            disabled={adding || !label.trim() || !value.trim()}
            className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-green/10 text-green hover:bg-green/20 transition-colors disabled:opacity-50 text-xs font-medium shrink-0"
          >
            {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            Add
          </button>
        </div>
      )}
      {error && <p className="shrink-0 text-xs text-red">{error}</p>}

      <div className="flex-1 overflow-y-auto space-y-2">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="h-5 w-5 text-green animate-spin" />
          </div>
        ) : !active ? (
          <div className="flex flex-col items-center justify-center h-full text-overlay0">
            <Table2 className="h-10 w-10 mb-2 opacity-30" />
            <p className="text-sm">Select a {mode} to view data points</p>
          </div>
        ) : points.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-overlay0">
            <Table2 className="h-10 w-10 mb-2 opacity-30" />
            <p className="text-sm">No data points yet</p>
          </div>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-left text-overlay0 border-b border-white/10">
                <th className="px-3 py-2 font-medium">Label</th>
                <th className="px-3 py-2 font-medium">Value</th>
                <th className="px-3 py-2 font-medium">Unit</th>
                <th className="px-3 py-2 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {points.map((dp) => (
                <tr key={dp.id} className="border-b border-white/5 hover:bg-white/5">
                  <td className="px-3 py-2 text-text">{dp.label}</td>
                  <td className="px-3 py-2 text-text font-medium">{dp.value}</td>
                  <td className="px-3 py-2 text-overlay0">{dp.unit || ''}</td>
                  <td className="px-3 py-2">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] ${dp.confidence === 'high' ? 'bg-green/10 text-green' : dp.confidence === 'medium' ? 'bg-yellow/10 text-yellow' : 'bg-red/10 text-red'}`}>
                      {dp.confidence || 'medium'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* ── Tab 4: Charts ───────────────────────────────────────────── */

function ChartsTab() {
  const {
    researchList, projectList, activeResearch, activeProject,
    selectResearch, selectProject, generateResearchChart, generateProjectChart,
  } = useDataAnalysis()
  const [mode, setMode] = useState<'research' | 'project'>('research')
  const [chartType, setChartType] = useState('auto')
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<{ chart_type: string; data_points: number; url?: string; title?: string } | null>(null)
  const [error, setError] = useState('')
  const [history, setHistory] = useState<ChartOutput[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [selectedOutput, setSelectedOutput] = useState<ChartOutput | null>(null)

  const active = mode === 'research' ? activeResearch : activeProject
  const pointCount = active?.data_points?.length ?? 0

  const loadHistory = useCallback(async () => {
    if (!active) {
      setHistory([])
      return
    }
    setHistoryLoading(true)
    try {
      const list = mode === 'research' && activeResearch
        ? await api.listResearchOutputs(activeResearch.topic)
        : activeProject
          ? await api.listProjectOutputs(activeProject.id)
          : []
      setHistory(list)
      setSelectedOutput((cur) => cur && list.some((o) => o.dir === cur.dir) ? cur : (list[0] ?? null))
    } catch {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }, [mode, active, activeResearch, activeProject])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  useEffect(() => {
    const handleArtifact = (e: Event) => {
      if (!active) return
      const url = (e as CustomEvent).detail?.url as string | undefined
      if (!url) return
      loadHistory()
      if (url && history.some((o) => url.includes(o.dir))) {
        const match = history.find((o) => url.includes(o.dir))
        if (match) setSelectedOutput(match)
      }
    }
    window.addEventListener('open-artifact', handleArtifact)
    return () => window.removeEventListener('open-artifact', handleArtifact)
  }, [active, history, loadHistory])

  const handleGenerate = async () => {
    if (!active || pointCount === 0) return
    setGenerating(true)
    setError('')
    setResult(null)
    try {
      const res = mode === 'research' && activeResearch
        ? await generateResearchChart(activeResearch.topic, chartType)
        : activeProject
          ? await generateProjectChart(activeProject.id, chartType)
          : null
      if (!res) {
        setError('No target selected')
        return
      }
      setResult(res)
      const url = res.relative_url || res.url
      if (url) window.open(url, '_blank')
      loadHistory()
    } catch (err: any) {
      setError(err.message || 'Failed to generate chart')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="flex flex-col h-full gap-4">
      <div className="shrink-0 flex items-center gap-2">
        <button
          onClick={() => setMode('research')}
          className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${mode === 'research' ? 'bg-purple/10 text-purple' : 'text-overlay0 hover:text-text hover:bg-white/5'}`}
        >
          Research
        </button>
        <button
          onClick={() => setMode('project')}
          className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${mode === 'project' ? 'bg-amber/10 text-amber' : 'text-overlay0 hover:text-text hover:bg-white/5'}`}
        >
          Project
        </button>
        <div className="flex-1" />
        <select
          value={mode === 'research' ? (activeResearch?.topic ?? '') : (activeProject?.id ?? '')}
          onChange={(e) => mode === 'research' ? selectResearch(e.target.value) : selectProject(e.target.value)}
          className="bg-black/60 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-text outline-none focus:ring-1 focus:ring-green/50 max-w-[220px]"
        >
          <option value="">Select {mode}…</option>
          {mode === 'research'
            ? researchList.map((r) => <option key={r.id} value={r.topic}>{r.topic}</option>)
            : projectList.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </div>

      {active && (
        <div className="shrink-0 bg-surface0/50 rounded-xl p-4 border border-white/5">
          <p className="text-sm text-text mb-1 font-medium">
            {mode === 'research' && activeResearch ? activeResearch.topic : activeProject?.name ?? ''}
          </p>
          <p className="text-xs text-overlay0 mb-3">
            {pointCount} data points · chart type will be auto-detected from data shape unless overridden
          </p>
          <div className="flex items-center gap-2">
            <select
              value={chartType}
              onChange={(e) => setChartType(e.target.value)}
              className="bg-black/60 border border-white/10 rounded-xl px-3 py-1.5 text-xs text-text outline-none focus:ring-1 focus:ring-green/50"
            >
              <option value="auto">Auto</option>
              <option value="line">Line</option>
              <option value="bar">Bar</option>
              <option value="pie">Pie</option>
            </select>
            <button
              onClick={handleGenerate}
              disabled={generating || pointCount === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-green/10 text-green hover:bg-green/20 transition-colors disabled:opacity-50 text-sm font-medium"
            >
              {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <BarChart3 className="h-4 w-4" />}
              {generating ? 'Generating…' : 'Generate Chart'}
            </button>
          </div>
          {error && <p className="text-xs text-red mt-2">{error}</p>}
          {result && (
            <div className="mt-3 flex items-center gap-2 text-xs text-subtext1">
              <span className="px-2 py-0.5 rounded-full bg-green/10 text-green">{result.chart_type}</span>
              <span>{result.data_points} points</span>
              {result.url && (
                <a
                  href={result.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-green hover:text-text transition-colors"
                >
                  <ExternalLink className="h-3 w-3" />
                  Open Chart
                </a>
              )}
            </div>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0 flex flex-col gap-3 overflow-y-auto">
        <div className="shrink-0 flex items-center justify-between">
          <p className="text-xs font-medium text-text uppercase tracking-wider">Chart History</p>
          {historyLoading && <Loader2 className="h-3.5 w-3.5 text-green animate-spin" />}
        </div>

        {!active ? (
          <div className="flex flex-col items-center justify-center h-full text-overlay0">
            <BarChart3 className="h-10 w-10 mb-2 opacity-30" />
            <p className="text-sm">Select a {mode} to view generated charts</p>
          </div>
        ) : history.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-overlay0">
            <BarChart3 className="h-10 w-10 mb-2 opacity-30" />
            <p className="text-sm">No charts generated yet for this {mode}</p>
          </div>
        ) : (
          <>
            <div className="shrink-0 space-y-1.5">
              {history.map((output) => (
                <button
                  key={output.dir}
                  onClick={() => setSelectedOutput(output)}
                  className={`w-full flex items-center gap-3 rounded-xl px-3 py-2 border text-left transition-colors ${
                    selectedOutput?.dir === output.dir
                      ? 'bg-green/10 border-green/30'
                      : 'bg-surface0/50 border-white/5 hover:border-white/15'
                  }`}
                >
                  <div className="w-8 h-8 rounded-lg bg-green/10 flex items-center justify-center shrink-0">
                    <BarChart3 className="h-4 w-4 text-green" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-text truncate">
                      {output.chart_type} chart · {output.data_points} points
                    </p>
                    <p className="text-xs text-overlay0">{output.created_at}</p>
                  </div>
                  <ExternalLink className="h-3.5 w-3.5 text-overlay0 shrink-0" />
                </button>
              ))}
            </div>

            {selectedOutput && (
              <div className="flex-1 min-h-0 flex flex-col gap-2">
                <div className="shrink-0 flex items-center justify-between">
                  <p className="text-xs text-subtext1">
                    {selectedOutput.chart_type} · {selectedOutput.data_points} points · {selectedOutput.created_at}
                  </p>
                  <a
                    href={selectedOutput.relative_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-xs text-green hover:text-text transition-colors"
                  >
                    <ExternalLink className="h-3 w-3" />
                    Open in new tab
                  </a>
                </div>
                <iframe
                  src={selectedOutput.relative_url}
                  title={`Chart ${selectedOutput.dir}`}
                  className="flex-1 w-full min-h-[300px] rounded-xl bg-black/60 border border-white/10"
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/* ── Main Panel ──────────────────────────────────────────────── */

const tabs: { id: Tab; label: string; icon: typeof Database }[] = [
  { id: 'import', label: 'Import', icon: Upload },
  { id: 'web', label: 'Web Research', icon: Globe },
  { id: 'points', label: 'Data Points', icon: Table2 },
  { id: 'charts', label: 'Charts', icon: BarChart3 },
]

export function AnalysisPanel() {
  const [tab, setTab] = useState<Tab>('import')

  return (
    <div className="flex flex-col h-full bg-crust p-4 sm:p-6">
      <div className="flex items-center justify-between mb-4 shrink-0">
        <h1 className="text-lg font-bold text-text flex items-center gap-2">
          <Database className="h-5 w-5 text-green" />
          Data Analysis
        </h1>
        <div className="flex items-center gap-1 bg-black/60 border border-white/10 rounded-full px-1.5 py-1">
          {tabs.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all ${
                tab === id ? 'bg-green/10 text-green' : 'text-overlay0 hover:text-text hover:bg-white/5'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">{label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0">
        {tab === 'import' && <ImportTab />}
        {tab === 'web' && <WebResearchTab />}
        {tab === 'points' && <DataPointsTab />}
        {tab === 'charts' && <ChartsTab />}
      </div>
    </div>
  )
}