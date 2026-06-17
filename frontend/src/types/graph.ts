export interface GraphNode {
  id: string
  type: string
  label: string
  properties: Record<string, unknown>
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  relation: string
  properties: Record<string, unknown>
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}
