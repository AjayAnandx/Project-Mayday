import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

// OpenUI auto-mounts an "Inspect" devtools widget in development by importing an unpinned
// bundle from cdn.jsdelivr.net. Keep remote code out of Mayday: mark it as already mounted.
// (Production builds strip it anyway.)
;(globalThis as Record<symbol, unknown>)[Symbol.for('openui.devtools.autoMount')] = true

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
