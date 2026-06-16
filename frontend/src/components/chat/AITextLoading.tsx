import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { cn } from '../../lib/utils'

interface AITextLoadingProps {
  texts?: string[]
  className?: string
  interval?: number
}

const defaultTexts = [
  'Thinking...',
  'Processing...',
  'Checking your data...',
  'Working on it...',
  'Almost there...',
]

export function AITextLoading({
  texts = defaultTexts,
  className,
  interval = 2000,
}: AITextLoadingProps) {
  const [currentTextIndex, setCurrentTextIndex] = useState(0)

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTextIndex((prevIndex) => (prevIndex + 1) % texts.length)
    }, interval)
    return () => clearInterval(timer)
  }, [interval, texts.length])

  return (
    <div className="flex items-center justify-center py-6">
      <motion.div
        animate={{ opacity: 1 }}
        className="relative w-full px-4 py-2"
        initial={{ opacity: 0 }}
        transition={{ duration: 0.4 }}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={currentTextIndex}
            animate={{
              opacity: 1,
              y: 0,
              backgroundPosition: ['200% center', '-200% center'],
            }}
            className={cn(
              'flex min-w-max justify-center whitespace-nowrap bg-[length:200%_100%] bg-gradient-to-r from-text via-overlay0 to-text bg-clip-text font-semibold text-sm text-transparent',
              className,
            )}
            exit={{ opacity: 0, y: -20 }}
            initial={{ opacity: 0, y: 20 }}
            transition={{
              opacity: { duration: 0.3 },
              y: { duration: 0.3 },
              backgroundPosition: {
                duration: 2.5,
                ease: 'linear',
                repeat: Infinity,
              },
            }}
          >
            {texts[currentTextIndex]}
          </motion.div>
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
