import { useEffect, useState } from 'react'
import { Mail, Send } from 'lucide-react'
import { cn } from '../../lib/utils'
import { api } from '../../services/api'
import { Modal } from '../ui/Modal'
import type { DigestPreview } from '../../types/planner'

/** Preview the morning/evening email digest and send it now. */
export function DigestModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [kind, setKind] = useState<'morning' | 'evening'>('morning')
  const [preview, setPreview] = useState<DigestPreview | null>(null)
  const [status, setStatus] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setStatus(null)
    api.planner.digest(kind).then(setPreview).catch(() => setPreview(null))
  }, [open, kind])

  const send = async () => {
    setStatus('Sending…')
    try {
      const r = await api.planner.sendDigest(kind)
      setStatus(r.sent ? `Sent “${r.subject}”` : `Not sent: ${r.reason}`)
    } catch (e) {
      setStatus(e instanceof Error ? e.message : 'Failed')
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Email digest">
      <div className="space-y-4">
        <div className="flex rounded-[10px] bg-white/[0.04] border border-white/[0.06] p-0.5 w-fit" role="tablist">
          {(['morning', 'evening'] as const).map(k => (
            <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
                    className={cn('px-3 py-1 rounded-[8px] text-[11px] font-medium capitalize',
                      kind === k ? 'bg-text text-black' : 'text-subtext0 hover:text-text')}>
              {k} · {k === 'morning' ? preview?.morning ?? '07:30' : preview?.evening ?? '21:00'}
            </button>
          ))}
        </div>
        {preview ? (
          <div className="rounded-2xl bg-white/[0.03] border border-white/[0.05] p-4 space-y-3 max-h-[50vh] overflow-y-auto">
            <p className="text-sm font-medium text-text">{preview.subject}</p>
            {preview.sections.map(([h, lines]) => (
              <div key={h}>
                <p className="text-[11px] font-semibold text-green mb-1">{h}</p>
                <ul className="text-xs text-subtext1 space-y-0.5 list-disc pl-4">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul>
              </div>
            ))}
          </div>
        ) : <p className="text-xs text-overlay1">Loading preview…</p>}
        <p className="flex items-center gap-1.5 text-[11px] text-overlay1">
          <Mail className="h-3 w-3" />
          {preview?.to
            ? <>Sends automatically to <span className="text-subtext1">{preview.to}</span> from the Mayday mailbox{preview.enabled ? '' : ' (disabled in config)'}.</>
            : <>No recipient yet — set <code className="text-subtext1">planner.digest.to</code> or <code className="text-subtext1">gmail.user_email</code> in config.yaml.</>}
        </p>
        <div className="flex items-center gap-3">
          <button onClick={send} disabled={!preview?.to}
                  className="flex items-center gap-1.5 rounded-xl bg-green text-black text-xs font-semibold px-3 py-2 hover:bg-green/90 disabled:opacity-40">
            <Send className="h-3.5 w-3.5" /> Send now
          </button>
          {status && <span className="text-[11px] text-subtext0">{status}</span>}
        </div>
      </div>
    </Modal>
  )
}
