import { useRef, useCallback } from 'react'

interface UseAutoResizeTextareaProps {
  minHeight: number
  maxHeight: number
}

export function useAutoResizeTextarea({ minHeight, maxHeight }: UseAutoResizeTextareaProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const adjustHeight = useCallback(
    (reset?: boolean) => {
      const textarea = textareaRef.current
      if (!textarea) return

      if (reset) {
        textarea.style.height = `${minHeight}px`
        return
      }

      textarea.style.height = `${minHeight}px`
      const scrollHeight = textarea.scrollHeight
      textarea.style.height = `${Math.min(Math.max(scrollHeight, minHeight), maxHeight)}px`
    },
    [minHeight, maxHeight],
  )

  return { textareaRef, adjustHeight }
}
