import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { AlarmClock, Check } from 'lucide-react'
import { api } from '../../services/api'
import { notifyPlannerChanged } from '../../lib/planner'
import { sendSignal } from '../../services/brainSignals'

interface ReminderEvent {
  id: string
  title: string
  body: string
  category: string
  item_id?: string
  actions?: ('done' | 'snooze')[]
}

export function ReminderDialog() {
  const [reminders, setReminders] = useState<ReminderEvent[]>([])

  const dismiss = useCallback((id: string) => {
    sendSignal('ui_dismiss', { surface: 'reminder' }, id)
    setReminders(prev => prev.filter(r => r.id !== id))
  }, [])

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as ReminderEvent
      setReminders(prev => {
        if (prev.find(r => r.id === detail.id)) return prev
        return [...prev, detail]
      })
    }
    window.addEventListener('reminder-fired', handler)
    return () => window.removeEventListener('reminder-fired', handler)
  }, [])

  if (reminders.length === 0) return null

  const latest = reminders[reminders.length - 1]

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn()
      notifyPlannerChanged()
    } finally {
      dismiss(latest.id)
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        key={latest.id}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
        onClick={() => dismiss(latest.id)}
      >
        <motion.div
          role="alertdialog"
          aria-labelledby="reminder-title"
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          transition={{ type: 'spring', duration: 0.3 }}
          className="bg-[#0f0f0f] border border-green/40 rounded-3xl p-6 max-w-sm w-full mx-4 shadow-2xl"
          onClick={e => e.stopPropagation()}
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="w-2 h-2 rounded-full bg-green animate-pulse" />
            <p id="reminder-title" className="text-green font-bold text-lg">{latest.title || 'Reminder'}</p>
            {reminders.length > 1 && <span className="ml-auto text-[11px] text-overlay1">+{reminders.length - 1} more</span>}
          </div>
          <p className="text-text text-base mb-6">{latest.body}</p>
          {latest.item_id ? (
            <div className="space-y-2">
              <button
                onClick={() => act(() => api.planner.complete(latest.item_id!, true))}
                className="w-full flex items-center justify-center gap-2 rounded-full bg-green text-crust font-semibold py-2.5 hover:brightness-110 transition-all"
              >
                <Check className="h-4 w-4" /> Done
              </button>
              <div className="grid grid-cols-3 gap-2">
                {[{ m: 10, l: '10 min' }, { m: 60, l: '1 hour' }, { m: 24 * 60, l: 'Tomorrow' }].map(s => (
                  <button key={s.m}
                          onClick={() => act(() => api.planner.snooze(latest.item_id!, { minutes: s.m }))}
                          className="flex items-center justify-center gap-1 rounded-full bg-white/[0.06] text-subtext1 text-xs py-2 hover:bg-white/[0.1]">
                    <AlarmClock className="h-3 w-3" /> {s.l}
                  </button>
                ))}
              </div>
              <button onClick={() => dismiss(latest.id)} className="w-full text-xs text-overlay1 hover:text-text py-1">Dismiss</button>
            </div>
          ) : (
            <button
              onClick={() => dismiss(latest.id)}
              className="w-full rounded-full bg-green text-crust font-semibold py-2.5 hover:brightness-110 transition-all"
            >
              Dismiss
            </button>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
