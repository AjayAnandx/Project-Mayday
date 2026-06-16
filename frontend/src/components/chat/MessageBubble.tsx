import type { ChatMessage } from '../../hooks/useChat'

interface MessageBubbleProps {
  message: ChatMessage
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isTool = message.role === 'tool'

  if (isTool) {
    return (
      <div className="flex justify-center my-1.5">
        <div className="bg-surface0/40 border border-surface1/50 rounded-full px-3 py-1 text-[11px] text-subtext0 max-w-[65%] flex items-center gap-1.5">
          <span className="text-green font-mono text-[9px] uppercase tracking-wider font-semibold">
            {message.tool_name}
          </span>
          <span className="opacity-60 truncate">{message.content}</span>
        </div>
      </div>
    )
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} my-1`}>
      <div
        className={`max-w-[65%] px-3.5 py-2 text-[13px] leading-snug rounded-full ${
          isUser
            ? 'bg-green/15 text-text'
            : 'bg-surface0/50 text-text'
        }`}
      >
        {message.content}
      </div>
    </div>
  )
}
