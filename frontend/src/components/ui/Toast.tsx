import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { AlarmClock, Check, X } from 'lucide-react'
import { subscribeToasts, type Toast } from '../../hooks/useNotifications'
import { api } from '../../services/api'
import { notifyPlannerChanged } from '../../lib/planner'
import { sendSignal } from '../../services/brainSignals'

type Outcome = 'accepted' | 'later' | 'less' | 'dismissed'

async function suggestionOutcome(id: string, outcome: Outcome): Promise<{ result?: { offer_autonomy?: string } } | null> {
  try {
    const r = await fetch(`/api/brain/suggestions/${id}/${outcome}`, { method: 'POST' })
    return r.ok ? await r.json() : null
  } catch { return null }
}

const btn = 'rounded-lg px-2.5 py-1 text-[11px] transition-colors'
const primary = `${btn} bg-green text-black font-semibold hover:bg-green/90`
const secondary = `${btn} bg-white/[0.06] text-subtext1 hover:bg-white/[0.1]`

// Brain V3: Do it / Not now / Less of this (+ options for "your call", Undo for things Mayday did)
function SuggestionActions({ t, onDone }: { t: Toast; onDone: () => void }) {
  const [showWhy, setShowWhy] = useState(false)
  const [offer, setOffer] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const id = t.suggestion_id!

  const respond = async (outcome: Outcome) => {
    setBusy(true)
    const res = await suggestionOutcome(id, outcome)
    setBusy(false)
    if (outcome === 'accepted') notifyPlannerChanged()
    if (outcome === 'accepted' && t.chat_prompt) {
      window.dispatchEvent(new CustomEvent('navigate', { detail: 'chat' }))
      window.dispatchEvent(new CustomEvent('mayday-chat-send', { detail: t.chat_prompt }))
    }
    if (res?.result?.offer_autonomy) { setOffer(res.result.offer_autonomy); return }
    onDone()
  }
  const choose = async (i: number) => {
    setBusy(true)
    try { await fetch(`/api/brain/suggestions/${id}/choose/${i}`, { method: 'POST' }) } catch { /* ignore */ }
    setBusy(false)
    notifyPlannerChanged()
    onDone()
  }
  const undo = async () => {
    if (t.action_id) {
      try { await fetch(`/api/brain/actions/${t.action_id}/undo`, { method: 'POST' }) } catch { /* ignore */ }
      notifyPlannerChanged()
    }
    await suggestionOutcome(id, 'dismissed')
    onDone()
  }
  const allow = async (allowed: boolean) => {
    if (offer) {
      try {
        await fetch('/api/brain/proactive/preauthorize', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind: offer, allowed }),
        })
      } catch { /* ignore */ }
    }
    onDone()
  }

  if (offer) {
    return (
      <div className="mt-2.5 text-[11px] text-subtext1">
        <p>You've approved this 5 times in a row. Let Mayday do it on its own next time (you can always undo)?</p>
        <div className="flex gap-1.5 mt-1.5">
          <button className={primary} onClick={() => allow(true)}>Yes, automatically</button>
          <button className={secondary} onClick={() => allow(false)}>Keep asking</button>
        </div>
      </div>
    )
  }
  return (
    <div className="mt-2.5">
      <div className="flex flex-wrap gap-1.5">
        {t.mode === 'framing' && (t.options || []).map((o, i) => (
          <button key={i} disabled={busy} className={i === 0 ? primary : secondary} onClick={() => choose(i)}>{o}</button>
        ))}
        {t.mode === 'nudge' && (
          <button disabled={busy} className={primary} onClick={() => respond('accepted')}>{t.has_action ? 'Do it' : 'OK'}</button>
        )}
        {t.mode === 'autonomous' ? (
          <>
            <button className={secondary} onClick={undo}>Undo</button>
            <button className={secondary} onClick={() => respond('accepted')}>Good</button>
          </>
        ) : (
          <>
            <button disabled={busy} className={secondary} onClick={() => respond('later')}>Not now</button>
            <button disabled={busy} className={secondary} onClick={() => respond('less')}>Less of this</button>
          </>
        )}
        {t.why && (
          <button className={`${btn} text-overlay1 hover:text-text`} onClick={() => setShowWhy(v => !v)} aria-expanded={showWhy}>
            Why?
          </button>
        )}
      </div>
      {showWhy && t.why && <p className="mt-1.5 text-[11px] text-overlay1 italic">{t.why}</p>}
    </div>
  )
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([])

  useEffect(() => {
    const unsub = subscribeToasts((t) => {
      setToasts(prev => {
        if (!t.title && !t.body) {
          return prev.filter(x => x.id !== t.id.replace('_dismiss', ''))
        }
        return prev.some(x => x.id === t.id) ? prev : [...prev, t]
      })
      // plain toasts disappear on their own; planner toasts wait for an action
      if (!t.item_id && !t.suggestion_id) {
        setTimeout(() => setToasts(prev => prev.filter(x => x.id !== t.id)), 4500)
      }
    })
    return unsub
  }, [])

  const remove = (id: string) => setToasts(prev => prev.filter(x => x.id !== id))
  // explicit ✕ = a dismissal signal; removal after Done/Snooze is not
  const close = (id: string) => {
    const t = toasts.find(x => x.id === id)
    if (t?.suggestion_id) {
      void suggestionOutcome(t.suggestion_id, 'dismissed')   // learned as a dismissal of this type
    } else {
      sendSignal('ui_dismiss', { surface: 'toast' }, id)
    }
    remove(id)
  }

  const act = async (t: Toast, action: 'done' | 'snooze') => {
    if (!t.item_id) return
    try {
      if (action === 'done') await api.planner.complete(t.item_id, true)
      else await api.planner.snooze(t.item_id, { minutes: 10 })
      notifyPlannerChanged()
    } finally {
      remove(t.id)
    }
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2" role="region" aria-label="Notifications">
      <AnimatePresence>
        {toasts.map(t => (
          <motion.div
            key={t.id}
            role="status"
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="bg-[#0f0f0f] border border-green/30 rounded-2xl px-4 py-3 shadow-xl w-80 max-w-[calc(100vw-3rem)]"
          >
            <div className="flex items-start gap-2">
              <div className="flex-1 min-w-0">
                <p className="text-green text-sm font-semibold">{t.title}</p>
                <p className="text-text text-sm mt-0.5">{t.body}</p>
              </div>
              <button onClick={() => close(t.id)} aria-label="Dismiss" className="p-0.5 text-overlay1 hover:text-text">
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            {t.suggestion_id && <SuggestionActions t={t} onDone={() => remove(t.id)} />}
            {t.item_id && t.actions && t.actions.length > 0 && (
              <div className="flex gap-1.5 mt-2.5">
                {t.actions.includes('done') && (
                  <button onClick={() => act(t, 'done')}
                          className="flex items-center gap-1 rounded-lg bg-green text-black px-2.5 py-1 text-[11px] font-semibold hover:bg-green/90">
                    <Check className="h-3 w-3" /> Done
                  </button>
                )}
                {t.actions.includes('snooze') && (
                  <button onClick={() => act(t, 'snooze')}
                          className="flex items-center gap-1 rounded-lg bg-white/[0.06] text-subtext1 px-2.5 py-1 text-[11px] hover:bg-white/[0.1]">
                    <AlarmClock className="h-3 w-3" /> Snooze 10m
                  </button>
                )}
              </div>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
