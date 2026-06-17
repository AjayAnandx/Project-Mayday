import { useState, useCallback } from 'react'
import { Search, RefreshCw, BrainCircuit } from 'lucide-react'
import { useGraph } from '../../hooks/useGraph'
import { GraphCanvas } from './GraphCanvas'
import { NodeDetail } from './NodeDetail'
import type { GraphNode, GraphData } from '../../types/graph'

export function BrainPanel() {
  const { graphData, loading, error, fetchGraph, searchGraph, fetchNode } = useGraph()
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedNode, setSelectedNode] = useState<{ node: GraphNode; subgraph: GraphData } | null>(null)

  const handleSearch = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    if (searchQuery.trim()) {
      searchGraph(searchQuery.trim())
    }
  }, [searchQuery, searchGraph])

  const handleNodeClick = useCallback(async (nodeId: string) => {
    const result = await fetchNode(nodeId)
    if (result) {
      setSelectedNode(result)
    }
  }, [fetchNode])

  const handleNavigate = useCallback(async (nodeId: string) => {
    const result = await fetchNode(nodeId)
    if (result) {
      setSelectedNode(result)
    }
  }, [fetchNode])

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-6 py-3 border-b border-surface1">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-green/30 to-purple-500/30 flex items-center justify-center">
            <BrainCircuit className="h-4 w-4 text-green" />
          </div>
          <h2 className="text-sm font-semibold text-text">Brain</h2>
        </div>

        <div className="flex items-center gap-3">
          <form onSubmit={handleSearch} className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-overlay0" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search memory..."
              className="w-56 pl-9 pr-3 py-1.5 text-xs bg-surface0 border border-surface1 rounded-xl text-text placeholder-overlay0 focus:outline-none focus:ring-1 focus:ring-green/50 focus:border-green/50 transition-all"
            />
          </form>
          <button
            onClick={fetchGraph}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-overlay0 hover:text-text bg-surface0 hover:bg-surface1 rounded-full transition-colors"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      <div className="flex-1 relative">
        {loading && !graphData && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex gap-1">
              <div className="w-2 h-2 bg-green rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <div className="w-2 h-2 bg-green rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <div className="w-2 h-2 bg-green rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <BrainCircuit className="h-10 w-10 text-overlay0 mx-auto mb-3" />
              <p className="text-sm text-overlay0">{error}</p>
              <button
                onClick={fetchGraph}
                className="mt-3 px-4 py-1.5 text-xs bg-green/10 text-green rounded-full hover:bg-green/20 transition-colors"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {!loading && !error && graphData && graphData.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <BrainCircuit className="h-12 w-12 text-overlay1 mx-auto mb-3" />
              <h3 className="text-base font-semibold text-text mb-1">Memory is empty</h3>
              <p className="text-xs text-overlay0 max-w-xs">
                Your knowledge graph will populate automatically as you create todos, events, and chat with Mayday.
              </p>
            </div>
          </div>
        )}

        {graphData && graphData.nodes.length > 0 && (
          <GraphCanvas
            nodes={graphData.nodes}
            edges={graphData.edges}
            onNodeClick={handleNodeClick}
            selectedNodeId={selectedNode?.node.id}
          />
        )}

        {selectedNode && (
          <NodeDetail
            node={selectedNode.node}
            subgraph={selectedNode.subgraph}
            onClose={() => setSelectedNode(null)}
            onNavigate={handleNavigate}
          />
        )}
      </div>
    </div>
  )
}
