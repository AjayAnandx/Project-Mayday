import { useState, useEffect, useCallback } from 'react'
import type { GraphData, GraphNode } from '../types/graph'
import { api } from '../services/api'

export function useGraph() {
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchGraph = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.fetchGraph()
      setGraphData(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load graph')
    } finally {
      setLoading(false)
    }
  }, [])

  const searchGraph = useCallback(async (query: string) => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.searchGraph(query)
      setGraphData(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchNode = useCallback(async (nodeId: string): Promise<{ node: GraphNode; subgraph: GraphData } | null> => {
    try {
      return await api.fetchNode(nodeId)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load node')
      return null
    }
  }, [])

  const deleteNode = useCallback(async (nodeId: string) => {
    try {
      await api.deleteNode(nodeId)
      await fetchGraph()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete node')
    }
  }, [fetchGraph])

  useEffect(() => {
    fetchGraph()
  }, [fetchGraph])

  return { graphData, loading, error, fetchGraph, searchGraph, fetchNode, deleteNode }
}
