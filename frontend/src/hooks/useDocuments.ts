import { useState, useEffect, useCallback } from 'react'
import { api } from '../services/api'
import type { DocumentMeta } from '../types/document'

export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  const load = useCallback(async (q?: string) => {
    setLoading(true)
    try {
      const data = q ? await api.searchDocuments(q) : await api.listDocuments()
      setDocuments(data)
    } catch {
      setDocuments([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const timer = setTimeout(() => load(search || undefined), 300)
    return () => clearTimeout(timer)
  }, [search, load])

  const upload = useCallback(async (file: File) => {
    const doc = await api.uploadDocument(file)
    await load(search || undefined)
    return doc
  }, [load, search])

  const remove = useCallback(async (id: string) => {
    await api.deleteDocument(id)
    setDocuments((prev) => prev.filter((d) => d.id !== id))
  }, [])

  const viewText = useCallback(async (id: string, pages?: string) => {
    return await api.getDocumentText(id, pages)
  }, [])

  return { documents, loading, search, setSearch, upload, remove, viewText, refresh: load }
}
