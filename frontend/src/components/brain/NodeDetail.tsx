import { X } from 'lucide-react'
import type { GraphNode, GraphData } from '../../types/graph'

const typeColors: Record<string, string> = {
  user: 'bg-green text-crust',
  todo: 'bg-yellow text-crust',
  event: 'bg-blue-500 text-white',
  concept: 'bg-purple-500 text-white',
  conversation: 'bg-overlay0 text-text',
  tag: 'bg-orange-500 text-crust',
  date: 'bg-overlay1 text-text',
}

interface NodeDetailProps {
  node: GraphNode
  subgraph: GraphData
  onClose: () => void
  onNavigate: (nodeId: string) => void
}

export function NodeDetail({ node, subgraph, onClose, onNavigate }: NodeDetailProps) {
  const connectedEdges = subgraph.edges.filter(
    e => e.source === node.id || e.target === node.id,
  )

  return (
    <div className="fixed left-0 right-0 bottom-0 sm:left-auto sm:right-4 sm:top-20 sm:w-80 bg-base border border-surface1 rounded-t-2xl sm:rounded-2xl shadow-2xl z-50 max-h-[70dvh] sm:max-h-[80vh] overflow-y-auto">
      <div className="flex items-center justify-between p-4 border-b border-surface1">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${typeColors[node.type] || 'bg-surface0 text-text'}`}>
            {node.type}
          </span>
          <span className="text-sm font-semibold text-text truncate max-w-[180px]">
            {node.label}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-overlay0 hover:text-text p-1 rounded-full hover:bg-surface0 transition-colors"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="p-4 space-y-4">
        {Object.keys(node.properties).length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-overlay1 uppercase tracking-wider mb-2">Properties</h4>
            <div className="space-y-1">
              {Object.entries(node.properties).map(([key, value]) => (
                <div key={key} className="flex gap-2 text-sm">
                  <span className="text-overlay0 min-w-[80px]">{key}:</span>
                  <span className="text-subtext1 truncate">{String(value)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {connectedEdges.length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-overlay1 uppercase tracking-wider mb-2">Connected ({connectedEdges.length})</h4>
            <div className="space-y-1">
              {connectedEdges.map(edge => {
                const isSource = edge.source === node.id
                const otherId = isSource ? edge.target : edge.source
                const otherNode = subgraph.nodes.find(n => n.id === otherId)
                return (
                  <button
                    key={edge.id}
                    onClick={() => onNavigate(otherId)}
                    className="w-full text-left flex items-center gap-2 text-sm p-1.5 rounded-lg hover:bg-surface0 transition-colors group"
                  >
                    <span className="text-overlay2 text-xs">{edge.relation}</span>
                    <span className="text-green group-hover:underline truncate">
                      {otherNode?.label || otherId}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
