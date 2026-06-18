import { useState, useEffect, useCallback } from 'react'
import type { Event, EventCreate, EventUpdate } from '../types/event'
import { api } from '../services/api'

export function useEvents() {
  const [events, setEvents] = useState<Event[]>([])
  const [loading, setLoading] = useState(true)

  const fetchEvents = useCallback(async () => {
    setLoading(true)
    try {
      const data = await api.listEvents()
      setEvents(data)
    } catch (err) {
      console.error('Failed to fetch events:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchEvents()
  }, [fetchEvents])

  const createEvent = async (data: EventCreate) => {
    await api.createEvent(data)
    await fetchEvents()
  }

  const updateEvent = async (id: string, data: EventUpdate) => {
    await api.updateEvent(id, data)
    await fetchEvents()
  }

  const deleteEvent = async (id: string) => {
    await api.deleteEvent(id)
    await fetchEvents()
  }

  return {
    events,
    loading,
    createEvent,
    updateEvent,
    deleteEvent,
  }
}
