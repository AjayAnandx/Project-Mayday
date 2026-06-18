import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { subscribeToasts, type Toast } from '../../hooks/useNotifications'

export function ToastContainer() {
  const [toasts, setToasts] = useState<(Toast & { visible: boolean })[]>([])

  useEffect(() => {
    const unsub = subscribeToasts((t) => {
      setToasts(prev => {
        if (!t.title && !t.body) {
          return prev.filter(x => x.id !== t.id.replace('_dismiss', ''))
        }
        return [...prev, { ...t, visible: true }]
      })
      // Auto-remove after animation
      setTimeout(() => {
        setToasts(prev => prev.filter(x => x.id !== t.id))
      }, 4500)
    })
    return unsub
  }, [])

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2">
      <AnimatePresence>
        {toasts.map(t => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="bg-surface1 border border-green/30 rounded-2xl px-4 py-3 shadow-xl max-w-sm cursor-pointer"
            onClick={() => {
              setToasts(prev => prev.filter(x => x.id !== t.id))
              window.focus()
            }}
          >
            <p className="text-green text-sm font-semibold">{t.title}</p>
            <p className="text-text text-sm mt-0.5">{t.body}</p>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
