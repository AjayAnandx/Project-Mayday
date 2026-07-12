import type { ChatMessage } from '../../hooks/useChat'
import { MarkdownRenderer } from './MarkdownRenderer'

interface MessageBubbleProps {
  message: ChatMessage
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isTool = message.role === 'tool'

  if (message.role === 'assistant' && !message.content && !isTool) {
    return null
  }

  if (isTool) {
    return (
      <div className="flex justify-center my-1.5 mx-2 sm:mx-0">
        <div className="bg-surface0/40 border border-surface1/50 rounded-lg px-2 sm:px-3 py-1.5 text-[11px] text-subtext0 min-w-0 w-full sm:w-auto">
          <div className="flex items-center gap-1.5 max-w-full">
            <span className="text-green font-mono text-[9px] uppercase tracking-wider font-semibold shrink-0">
              {message.tool_name}
            </span>
            <span className="opacity-60 truncate">{message.content}</span>
          </div>
          {message.image_url && (
            <div className="mt-1.5 rounded-md overflow-hidden border border-surface1/50">
              <img
                src={message.image_url}
                alt="Screenshot"
                className="max-h-64 w-full object-contain bg-black/20"
              />
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} my-1`}>
      <div
        className={`${
          isUser ? 'max-w-[75%] sm:max-w-[65%]' : 'max-w-[90%] sm:max-w-[80%]'
        } px-3 sm:px-3.5 py-2 text-[13px] leading-snug rounded-lg ${
          isUser
            ? 'bg-green/15 text-text'
            : 'bg-surface0/50 text-text'
        }`}
      >
        {isUser ? message.content : <MarkdownRenderer content={message.content} />}
      </div>
    </div>
  )
}
