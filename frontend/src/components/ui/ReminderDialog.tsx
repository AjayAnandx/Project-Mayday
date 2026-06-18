import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'motion/react'

interface ReminderEvent {
  id: string
  title: string
  body: string
  category: string
}

export function ReminderDialog() {
  const [reminders, setReminders] = useState<ReminderEvent[]>([])

  const dismiss = useCallback((id: string) => {
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
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          transition={{ type: 'spring', duration: 0.3 }}
          className="bg-surface0 border border-green/40 rounded-3xl p-6 max-w-sm w-full mx-4 shadow-2xl"
          onClick={e => e.stopPropagation()}
        >
          <div className="flex items-center gap-3 mb-3">
            <div className="w-2 h-2 rounded-full bg-green animate-pulse" />
            <p className="text-green font-bold text-lg">Reminder</p>
          </div>
          <p className="text-text text-base mb-6">{latest.body}</p>
          <button
            onClick={() => dismiss(latest.id)}
            className="w-full rounded-full bg-green text-crust font-semibold py-2.5 hover:brightness-110 transition-all"
          >
            Dismiss
          </button>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
