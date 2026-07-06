import type { WsMessage, WsResponse } from '../types/chat'

type WsCallback = (data: WsResponse) => void

export class ChatWebSocket {
  private ws: WebSocket | null = null
  private url: string
  private onMessage: WsCallback
  private onError?: (err: string) => void
  private onOpen?: () => void
  private onClose?: () => void
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private shouldReconnect = true

  constructor(
    url: string,
    callbacks: {
      onMessage: WsCallback
      onError?: (err: string) => void
      onOpen?: () => void
      onClose?: () => void
    },
  ) {
    this.url = url
    this.onMessage = callbacks.onMessage
    this.onError = callbacks.onError
    this.onOpen = callbacks.onOpen
    this.onClose = callbacks.onClose
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return
    this.shouldReconnect = true

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = this.url.startsWith('ws') ? this.url : `${protocol}//${window.location.host}${this.url}`
    this.ws = new WebSocket(wsUrl)

    this.ws.onopen = () => this.onOpen?.()
    this.ws.onclose = () => {
      this.onClose?.()
      if (this.shouldReconnect) {
        this.reconnectTimer = setTimeout(() => this.connect(), 3000)
      }
    }
    this.ws.onerror = () => this.onError?.('WebSocket error')
    this.ws.onmessage = (event) => {
      try {
        const data: WsResponse = JSON.parse(event.data)
        this.onMessage(data)
      } catch {
        this.onError?.('Failed to parse message')
      }
    }
  }

  send(msg: WsMessage) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  sendConfirmSkill(name: string) {
    this.send({ type: 'confirm_skill', name })
  }

  sendDismissSkill() {
    this.send({ type: 'dismiss_skill' })
  }

  disconnect() {
    this.shouldReconnect = false
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.ws?.close()
    this.ws = null
  }
}
