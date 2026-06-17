import { useEffect, useRef } from 'react'
import type { GraphNode, GraphEdge } from '../../types/graph'

const typeColors: Record<string, string> = {
  user: '#22c55e',
  todo: '#eab308',
  event: '#3b82f6',
  concept: '#a855f7',
  conversation: '#737373',
  tag: '#f97316',
  date: '#525252',
}

const typeShapes: Record<string, string> = {
  user: 'roundrectangle',
  todo: 'roundrectangle',
  event: 'roundrectangle',
  concept: 'ellipse',
  conversation: 'roundrectangle',
  tag: 'diamond',
  date: 'ellipse',
}

interface GraphCanvasProps {
  nodes: GraphNode[]
  edges: GraphEdge[]
  onNodeClick: (nodeId: string) => void
  selectedNodeId?: string
}

export function GraphCanvas({ nodes, edges, onNodeClick, selectedNodeId }: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<any>(null)

  useEffect(() => {
    let cytoscape: any
    let mounted = true

    async function init() {
      try {
        const cytoscapeModule = await import('cytoscape')
        cytoscape = cytoscapeModule.default || cytoscapeModule

        if (!mounted || !containerRef.current) return

        if (cyRef.current) {
          cyRef.current.destroy()
        }

        const cy = cytoscape({
          container: containerRef.current,
          style: [
            {
              selector: 'node',
              style: {
                'background-color': '#303030',
                'border-width': 2,
                'border-color': '#525252',
                'label': 'data(label)',
                'color': '#e5e5e5',
                'font-size': '10px',
                'text-valign': 'center',
                'text-halign': 'center',
                'width': 'label',
                'height': 'label',
                'padding': '8px',
                'shape': 'roundrectangle',
                'text-wrap': 'wrap',
                'text-max-width': '120px',
              },
            },
            {
              selector: 'edge',
              style: {
                'width': 1.5,
                'line-color': '#303030',
                'target-arrow-color': '#525252',
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
                'arrow-scale': 0.6,
              },
            },
            {
              selector: 'node:selected',
              style: {
                'border-color': '#22c55e',
                'border-width': 3,
              },
            },
            {
              selector: '.highlighted',
              style: {
                'border-color': '#22c55e',
                'border-width': 3,
              },
            },
          ],
          layout: {
            name: 'cose',
            animate: false,
            nodeRepulsion: () => 8000,
            idealEdgeLength: () => 120,
            gravity: 0.25,
            numIter: 1000,
          },
          elements: [
            ...nodes.map((n) => ({
              data: {
                id: n.id,
                label: n.label.length > 25 ? n.label.slice(0, 22) + '...' : n.label,
                type: n.type,
              },
              classes: n.type,
            })),
            ...edges.map((e) => ({
              data: {
                id: e.id,
                source: e.source,
                target: e.target,
                label: e.relation,
              },
            })),
          ],
          wheelSensitivity: 0.3,
        });

        (window as any).__cytoscape_graph = cy

        cy.nodes().forEach((node: any) => {
          const type = node.data('type')
          const color = typeColors[type] || '#525252'
          node.style('background-color', color)
          const shape = typeShapes[type] || 'roundrectangle'
          node.style('shape', shape)
        })

        cy.on('tap', 'node', (evt: any) => {
          const nodeId = evt.target.id()
          cy.nodes().removeClass('highlighted')
          evt.target.addClass('highlighted')
          onNodeClick(nodeId)
        })

        cy.on('tap', (evt: any) => {
          if (evt.target === cy) {
            cy.nodes().removeClass('highlighted')
          }
        })

        cyRef.current = cy
      } catch (e) {
        console.error('Failed to load cytoscape:', e)
      }
    }

    init()

    return () => {
      mounted = false
      if (cyRef.current) {
        cyRef.current.destroy()
        cyRef.current = null
      }
    }
  }, [nodes, edges, onNodeClick])

  useEffect(() => {
    if (cyRef.current && selectedNodeId) {
      const node = cyRef.current.getElementById(selectedNodeId)
      if (node.length) {
        cyRef.current.nodes().removeClass('highlighted')
        node.addClass('highlighted')
        cyRef.current.animate({
          fit: { eles: node, padding: 80 },
          duration: 300,
        })
      }
    }
  }, [selectedNodeId])

  return (
    <div
      ref={containerRef}
      className="w-full h-full"
      style={{ background: 'transparent' }}
    />
  )
}
