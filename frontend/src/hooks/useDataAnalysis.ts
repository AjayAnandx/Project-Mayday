import { useState, useEffect, useCallback } from 'react'
import { api } from '../services/api'
import type { ResearchProject } from '../types/research'
import type { Project } from '../types/project'

export interface ChartResult {
  chart_type: string
  data_points: number
  relative_url?: string
  url?: string
  title?: string
}

export function useDataAnalysis() {
  const [researchList, setResearchList] = useState<ResearchProject[]>([])
  const [projectList, setProjectList] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [activeResearch, setActiveResearch] = useState<ResearchProject | null>(null)
  const [activeProject, setActiveProject] = useState<Project | null>(null)

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const [research, projects] = await Promise.all([
        api.listResearch(),
        api.listProjects(),
      ])
      setResearchList(research)
      setProjectList(projects)
    } catch {
      setResearchList([])
      setProjectList([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const selectResearch = useCallback(async (topic: string) => {
    const top = researchList.find((r) => r.topic === topic)
    if (top) setActiveResearch(top)
    else {
      try {
        const detail = await api.getResearch(topic)
        setActiveResearch(detail)
      } catch {
        setActiveResearch(null)
      }
    }
  }, [researchList])

  const selectProject = useCallback(async (id: string) => {
    const proj = projectList.find((p) => p.id === id)
    if (proj) setActiveProject(proj)
    else {
      try {
        const detail = await api.getProject(id)
        setActiveProject(detail)
      } catch {
        setActiveProject(null)
      }
    }
  }, [projectList])

  const addResearchPoint = useCallback(async (topic: string, label: string, value: string, unit?: string) => {
    await api.addResearchDataPoint({ topic, label, value, unit })
    await selectResearch(topic)
    await loadAll()
  }, [selectResearch, loadAll])

  const addProjectPoint = useCallback(async (projectId: string, label: string, value: string, unit?: string) => {
    await api.addProjectDataPoint(projectId, { label, value, unit })
    await selectProject(projectId)
    await loadAll()
  }, [selectProject, loadAll])

  const generateResearchChart = useCallback(async (topic: string, chartType = 'auto', metric?: string): Promise<ChartResult> => {
    const res = await api.generateResearchChart({ topic, chart_type: chartType, metric })
    return {
      chart_type: res.chart_type,
      data_points: res.data_points,
      relative_url: res.relative_url || res.url,
      title: res.title,
    }
  }, [])

  const generateProjectChart = useCallback(async (projectId: string, chartType = 'auto', metric?: string): Promise<ChartResult> => {
    const res = await api.generateProjectChart(projectId, { chart_type: chartType, metric })
    return {
      chart_type: res.chart_type,
      data_points: res.data_points,
      relative_url: res.relative_url || res.url,
      title: res.title,
    }
  }, [])

  return {
    researchList,
    projectList,
    loading,
    activeResearch,
    activeProject,
    selectResearch,
    selectProject,
    addResearchPoint,
    addProjectPoint,
    generateResearchChart,
    generateProjectChart,
    refresh: loadAll,
  }
}