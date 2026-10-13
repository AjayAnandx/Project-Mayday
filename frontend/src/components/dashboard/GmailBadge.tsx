import { Mail, PlugZap } from 'lucide-react'
import { useGmail } from '../../hooks/useGmail'

export function GmailBadge() {
  const { status, unreadCount, loading, needsReconnect, connect } = useGmail()

  if (loading || !status?.enabled) return null

  if (!status.authenticated || needsReconnect) {
    return (
      <button
        onClick={connect}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-green bg-green/10 hover:bg-green/15 border border-green/30 rounded-full transition-colors"
        title={needsReconnect ?? 'Connect the dedicated Mayday mailbox'}
      >
        <PlugZap className="h-3.5 w-3.5" />
        <span>{needsReconnect ? 'Reconnect Gmail' : 'Connect Gmail for Mayday'}</span>
      </button>
    )
  }

  return (
    <div
      className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text bg-surface0/50 border border-surface2 rounded-full"
      title={status.agent_email}
    >
      <Mail className="h-3.5 w-3.5 text-green" />
      <span className="hidden sm:inline max-w-[180px] truncate">📧 {status.agent_email}</span>
      <span className="sm:hidden">📧</span>
      <span className="text-overlay0">• {unreadCount} unread</span>
    </div>
  )
}
