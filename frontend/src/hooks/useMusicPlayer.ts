import { useCallback, useEffect, useRef, useState } from 'react'
import type { MusicTrack } from '../types/music'

export interface PopoutTab {
  id: string
  videoId: string
  title: string
  artist: string
  thumb: string
  duration: string
  startTime: number
  isPlaying: boolean
}

interface UseMusicPlayerReturn {
  queue: MusicTrack[]
  current: MusicTrack | null
  currentIdx: number
  isPlaying: boolean
  currentTime: number
  duration: number
  volume: number
  repeat: boolean
  expanded: boolean
  needsGesture: boolean
  playError: string | null
  resolving: boolean
  openPopouts: PopoutTab[]
  setExpanded: (v: boolean) => void
  play: () => void
  pause: () => void
  next: () => void
  prev: () => void
  seek: (t: number) => void
  setVolume: (v: number) => void
  toggleRepeat: () => void
  toggleAutoPlay: () => void
  autoPlay: boolean
  jumpTo: (index: number) => void
  clearQueue: () => void
  handleMusicMessage: (data: any) => void
  videoRef: React.RefObject<HTMLVideoElement>
  audioRef: React.RefObject<HTMLAudioElement>
  openYouTube: () => string
  popoutVideo: (track?: MusicTrack | null) => string
  closeTab: (id: string) => void
  focusTab: (id: string) => void
  toggleTabPlay: (id: string) => void
}

const HISTORY_URL = '/api/music/history'
const PROXY_URL = (vid: string) => `/api/music/stream?video_id=${encodeURIComponent(vid)}`

export function useMusicPlayer(): UseMusicPlayerReturn {
  const [queue, setQueue] = useState<MusicTrack[]>([])
  const [currentIdx, setCurrentIdx] = useState<number>(-1)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume, setVolume] = useState(0.85)
  const [repeat, setRepeat] = useState(false)
  const [autoPlay, setAutoPlay] = useState<boolean>(() => {
    try { const v = localStorage.getItem('mayday_music_autoplay'); return v === null ? true : v !== 'false' } catch { return true }
  })
  const [expanded, setExpanded] = useState(false)
  const [needsGesture, setNeedsGesture] = useState(false)
  const [playError, setPlayError] = useState<string | null>(null)
  const [resolving, setResolving] = useState(false)
  const lastContextRef = useRef<{ mood?: string; language?: string; genre?: string; seedVideoId?: string }>({})
  const autoPlayRef = useRef(autoPlay)
  useEffect(() => { autoPlayRef.current = autoPlay; try { localStorage.setItem('mayday_music_autoplay', String(autoPlay)) } catch {} }, [autoPlay])

  const videoRef = useRef<HTMLVideoElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const resolvingRef = useRef(false)
  useEffect(() => { resolvingRef.current = resolving }, [resolving])
  const currentIdxRef = useRef(currentIdx)
  const queueRef = useRef(queue)

  useEffect(() => { currentIdxRef.current = currentIdx }, [currentIdx])
  useEffect(() => { queueRef.current = queue }, [queue])

  const currentTimeRef = useRef(currentTime)
  const isPlayingRef = useRef(isPlaying)
  useEffect(() => { currentTimeRef.current = currentTime }, [currentTime])
  useEffect(() => { isPlayingRef.current = isPlaying }, [isPlaying])
  const bcRef = useRef<BroadcastChannel | null>(null)
  // multi-tab: track open popout windows + their channels
  const [openPopouts, setOpenPopouts] = useState<PopoutTab[]>([])
  const popoutWindowsRef = useRef<Map<string, Window>>(new Map())
  const popoutChannelsRef = useRef<Map<string, BroadcastChannel>>(new Map())
  const popoutLastTimeRef = useRef<Map<string, number>>(new Map())
  const popoutPlayingRef = useRef<Map<string, boolean>>(new Map())

  const current: MusicTrack | null = currentIdx >= 0 && currentIdx < queue.length ? queue[currentIdx] : null
  const isAudioOnly = !!current?.is_audio_only || (!!current?.stream_url && /mime=audio/i.test(current.stream_url))

  const getActiveEl = useCallback((): HTMLMediaElement | null => {
    return isAudioOnly ? (audioRef.current as HTMLMediaElement | null) : (videoRef.current as HTMLMediaElement | null)
  }, [isAudioOnly])

  const getActiveElFor = useCallback((track: MusicTrack): HTMLMediaElement | null => {
    const audioOnly = !!(track as any)?.is_audio_only || (!!track.stream_url && /mime=audio/i.test(track.stream_url))
    return audioOnly ? (audioRef.current as HTMLMediaElement | null) : (videoRef.current as HTMLMediaElement | null)
  }, [])

  const getInactiveEl = useCallback((): HTMLMediaElement | null => {
    return isAudioOnly ? (videoRef.current as HTMLMediaElement | null) : (audioRef.current as HTMLMediaElement | null)
  }, [isAudioOnly])

  const getInactiveElFor = useCallback((track: MusicTrack): HTMLMediaElement | null => {
    const audioOnly = !!(track as any)?.is_audio_only || (!!track.stream_url && /mime=audio/i.test(track.stream_url))
    return audioOnly ? (videoRef.current as HTMLMediaElement | null) : (audioRef.current as HTMLMediaElement | null)
  }, [])

  const postHistory = useCallback(async (track: MusicTrack) => {
    if (!track.video_id) return
    try {
      await fetch(HISTORY_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_id: track.video_id,
          title: track.title,
          artist: track.artist,
          language: track.language,
          genre: (track as any).genre || track.language,
          mood: (track as any).mood || (track as any).genre || '',
          mood_id: (track as any).mood_id || (track as any).mood || '',
          thumb: track.thumb,
          duration: track.duration,
        }),
      })
    } catch {}
  }, [])

  const fetchStream = useCallback(async (video_id: string): Promise<{stream_url: string, is_audio_only?: boolean} | null> => {
    if (!video_id) return null
    try {
      const r = await fetch(`/api/music/resolve?video_id=${encodeURIComponent(video_id)}`)
      const j = await r.json()
      if (!r.ok) throw new Error(j.error || j.detail || 'resolve failed')
      if (j.stream_url) return { stream_url: j.stream_url, is_audio_only: !!j.is_audio_only }
      if (j.error) throw new Error(j.error)
      return null
    } catch (e: any) {
      console.warn('[music] fetchStream failed', video_id, e?.message || e)
      return null
    }
  }, [])

  const prefetchNext = useCallback((idx: number) => {
    const q = queueRef.current
    const nextIdx = idx + 1
    if (nextIdx < 0 || nextIdx >= q.length) return
    const nxt = q[nextIdx]
    if (!nxt || nxt.stream_url || !nxt.video_id) return
    // fire-and-forget, patch queue when done
    fetchStream(nxt.video_id).then(res => {
      if (!res?.stream_url) return
      setQueue(prev => {
        const copy = [...prev]
        if (copy[nextIdx]?.video_id === nxt.video_id && !copy[nextIdx].stream_url) {
          copy[nextIdx] = { ...copy[nextIdx], stream_url: res.stream_url, is_audio_only: !!res.is_audio_only }
        }
        return copy
      })
    })
  }, [fetchStream])

  const attemptPlay = useCallback((el: HTMLMediaElement | null, track: MusicTrack) => {
    if (!el || !track.stream_url) return
    const inactive = getInactiveElFor(track)
    if (inactive && inactive !== el) { try { inactive.pause(); inactive.removeAttribute('src'); inactive.load() } catch {} }
    setPlayError(null)
    setNeedsGesture(false)
    setResolving(false)
    el.src = track.stream_url
    el.load()
    el.volume = volume
    const p = el.play()
    if (p) p.then(() => {
      setIsPlaying(true); setNeedsGesture(false); setPlayError(null)
      // prefetch next 1 ahead for gapless queue
      prefetchNext(currentIdxRef.current)
    })
      .catch((e: any) => {
        console.warn('[music] autoplay blocked', e, track.stream_url.slice(0,80))
        if (e?.name === 'NotAllowedError' || /gesture|allow|interact/i.test(e?.message || '')) setNeedsGesture(true)
        else setPlayError(e?.message || 'Playback blocked — tap Play')
        setIsPlaying(false)
      })
    postHistory(track)
  }, [getInactiveElFor, postHistory, prefetchNext, volume])

  const loadCurrent = useCallback(async (track: MusicTrack) => {
    // lazy resolve: queued radio/mood items arrive with empty stream_url — fetch just-in-time
    let effectiveTrack = track
    if (!track.stream_url && track.video_id && !resolvingRef.current) {
      const snapIdx = currentIdxRef.current
      setResolving(true)
      setPlayError(null)
      const res = await fetchStream(track.video_id)
      setResolving(false)
      if (res?.stream_url) {
        effectiveTrack = { ...track, stream_url: res.stream_url, is_audio_only: !!res.is_audio_only }
        // patch queue so next/prev don't re-fetch — use snapIdx to avoid race
        setQueue(prev => {
          const copy = [...prev]
          if (copy[snapIdx]?.video_id === track.video_id) copy[snapIdx] = effectiveTrack
          return copy
        })
      } else {
        // auto-skip on resolve failure (accepted per user)
        const q = queueRef.current
        const idx = currentIdxRef.current
        if (q.length > idx + 1) {
          setTimeout(() => setCurrentIdx(idx + 1), 300)
        } else {
          setPlayError('No stream URL — try another track')
        }
        return
      }
    } else if (!effectiveTrack.stream_url) {
      const q = queueRef.current
      const idx = currentIdxRef.current
      if (q.length > idx + 1) setTimeout(() => setCurrentIdx(idx + 1), 300)
      else setPlayError('No stream URL — try another track')
      return
    }

    // Defer one tick so refs are mounted after queue update / patch
    setTimeout(() => {
      const el = getActiveElFor(effectiveTrack)
      if (!el) {
        setTimeout(() => {
          const retryEl = getActiveElFor(effectiveTrack)
          if (retryEl) attemptPlay(retryEl, effectiveTrack)
        }, 80)
        return
      }
      attemptPlay(el, effectiveTrack)
    }, 0)
  }, [attemptPlay, fetchStream])

  useEffect(() => {
    if (current) loadCurrent(current)
  }, [current?.video_id, current?.stream_url, current?.is_audio_only, loadCurrent])

  // Global gesture retry
  useEffect(() => {
    if (!needsGesture) return
    const retry = () => {
      const el = getActiveEl()
      if (!el) return
      el.play().then(() => { setNeedsGesture(false); setPlayError(null); setIsPlaying(true) }).catch(()=>{})
    }
    window.addEventListener('click', retry, { once: true })
    window.addEventListener('keydown', retry, { once: true })
    return () => { window.removeEventListener('click', retry); window.removeEventListener('keydown', retry) }
  }, [needsGesture, getActiveEl])

  // Bind media events to *both* elements (only active will fire, but we attach to both to avoid missing when isAudioOnly toggles)
  useEffect(() => {
    const attach = (el: HTMLMediaElement | null) => {
      if (!el) return () => {}
      const onTime = () => setCurrentTime(el.currentTime)
      const onDur = () => setDuration(el.duration || 0)
      const onEnded = () => {
        const idx = currentIdxRef.current
        const q = queueRef.current
        if (repeat && q.length === 1) { el.currentTime = 0; el.play().catch(()=>{}) ; return }
        if (idx + 1 < q.length) { setCurrentIdx(idx + 1); return }
        if (repeat && q.length > 0) { setCurrentIdx(0); return }
        // auto-play next in same genre/mood/language when queue exhausts
        if (!autoPlayRef.current) { setIsPlaying(false); return }
        const cur = q[idx] as any
        const ctx = lastContextRef.current
        const vid = cur?.video_id || ctx.seedVideoId || ''
        const lang = cur?.language || ctx.language || ''
        const mood = cur?.mood_id || cur?.mood || cur?.genre || ctx.mood || ctx.genre || ''
        if (!vid && !lang && !mood) { setIsPlaying(false); return }
        setResolving(true)
        const params = new URLSearchParams()
        if (vid) params.set('video_id', vid)
        if (lang) params.set('language', lang)
        if (mood) params.set('mood', mood)
        params.set('count', '5')
        fetch(`/api/music/next?${params.toString()}`).then(r=>r.json()).then(j=>{
          setResolving(false)
          if (j.track && j.track.video_id) {
            const newTracks: MusicTrack[] = [j.track, ...(j.queue || [])]
            setQueue(prev=>[...prev, ...newTracks])
            // advance to first new track
            setTimeout(()=> setCurrentIdx(idx+1), 50)
          } else {
            setIsPlaying(false)
          }
        }).catch(()=>{ setResolving(false); setIsPlaying(false) })
      }
      const onPlay = () => { setIsPlaying(true); setNeedsGesture(false); setPlayError(null) }
      const onPause = () => setIsPlaying(false)
      const onError = () => {
        const code = (el.error as any)?.code
        const msg = el.error?.message || `Media error ${code || ''}`.trim()
        const src = (el as HTMLMediaElement).currentSrc || ''
        console.warn('[music] media error', code, msg, src.slice(0,120), el.error)
        // CORS/unsupported source: try backend proxy fallback once
        if (current && !src.includes('/api/music/stream') && !src.includes('mime=audio') && playError === null) {
          // try proxy for this video_id
          const proxySrc = PROXY_URL(current.video_id)
          console.info('[music] retry via proxy', proxySrc)
          setPlayError('Retrying via proxy…')
          setTimeout(() => {
            const aEl = getActiveEl()
            if (aEl) { aEl.src = proxySrc; aEl.load(); aEl.play().catch(()=> setNeedsGesture(true)) }
          }, 200)
          return
        }
        setPlayError(msg || 'Stream failed — tap next or retry')
        setIsPlaying(false)
      }
      const onCanPlay = () => setPlayError(null)
      el.addEventListener('timeupdate', onTime)
      el.addEventListener('loadedmetadata', onDur)
      el.addEventListener('durationchange', onDur)
      el.addEventListener('ended', onEnded)
      el.addEventListener('play', onPlay)
      el.addEventListener('pause', onPause)
      el.addEventListener('error', onError)
      el.addEventListener('canplay', onCanPlay)
      return () => {
        el.removeEventListener('timeupdate', onTime)
        el.removeEventListener('loadedmetadata', onDur)
        el.removeEventListener('durationchange', onDur)
        el.removeEventListener('ended', onEnded)
        el.removeEventListener('play', onPlay)
        el.removeEventListener('pause', onPause)
        el.removeEventListener('error', onError)
        el.removeEventListener('canplay', onCanPlay)
      }
    }
    const detachV = attach(videoRef.current as unknown as HTMLMediaElement)
    const detachA = attach(audioRef.current as unknown as HTMLMediaElement)
    return () => { detachV(); detachA() }
  }, [repeat, current, playError, getActiveEl])

  useEffect(() => {
    if (videoRef.current) videoRef.current.volume = volume
    if (audioRef.current) audioRef.current.volume = volume
  }, [volume])

  useEffect(() => () => { try { bcRef.current?.close() } catch {} }, [])

  const play = useCallback(() => {
    const el = getActiveEl()
    if (!el) return
    setPlayError(null)
    const p = el.play()
    if (p) p.then(()=>{ setIsPlaying(true); setNeedsGesture(false) })
      .catch((e:any)=>{ if(e?.name==='NotAllowedError') setNeedsGesture(true); else setPlayError(e?.message||'Play failed'); })
  }, [getActiveEl])

  const pause = useCallback(() => { getActiveEl()?.pause() }, [getActiveEl])

  const next = useCallback(() => {
    const idx = currentIdxRef.current
    const q = queueRef.current
    if (idx + 1 < q.length) { setCurrentIdx(idx + 1); return }
    if (repeat && q.length > 0) { setCurrentIdx(0); return }
    if (!autoPlayRef.current) return
    const cur = q[idx] as any
    const ctx = lastContextRef.current
    const vid = cur?.video_id || ctx.seedVideoId || ''
    const lang = cur?.language || ctx.language || ''
    const mood = cur?.mood_id || cur?.mood || cur?.genre || ctx.mood || ctx.genre || ''
    if (!vid && !lang && !mood) return
    const params = new URLSearchParams()
    if (vid) params.set('video_id', vid)
    if (lang) params.set('language', lang)
    if (mood) params.set('mood', mood)
    params.set('count', '5')
    setResolving(true)
    fetch(`/api/music/next?${params.toString()}`).then(r=>r.json()).then(j=>{
      setResolving(false)
      if (j.track && j.track.video_id) {
        const newTracks: MusicTrack[] = [j.track, ...(j.queue || [])]
        setQueue(prev=>[...prev, ...newTracks])
        setTimeout(()=> setCurrentIdx(idx+1), 50)
      }
    }).catch(()=> setResolving(false))
  }, [repeat])

  const prev = useCallback(() => {
    const el = getActiveEl()
    if (el && el.currentTime > 3) { el.currentTime = 0; return }
    const idx = currentIdxRef.current
    if (idx > 0) setCurrentIdx(idx - 1)
    else if (repeat) setCurrentIdx(queueRef.current.length - 1)
  }, [repeat, getActiveEl])

  const seek = useCallback((t: number) => {
    const el = getActiveEl()
    if (!el) return
    el.currentTime = t
    setCurrentTime(t)
  }, [getActiveEl])

  const toggleRepeat = useCallback(() => setRepeat(r => !r), [])
  const toggleAutoPlay = useCallback(() => setAutoPlay(v => !v), [])
  const jumpTo = useCallback((index: number) => { if (index >= 0 && index < queueRef.current.length) setCurrentIdx(index) }, [])
  const clearQueue = useCallback(() => {
    setQueue([]); setCurrentIdx(-1); setIsPlaying(false); setNeedsGesture(false); setPlayError(null); setResolving(false)
    for (const el of [videoRef.current as unknown as HTMLMediaElement, audioRef.current as unknown as HTMLMediaElement]) {
      if (el) { try { el.pause(); el.removeAttribute('src'); el.load() } catch {} }
    }
  }, [])

  const openYouTube = useCallback((): string => {
    const cur = queueRef.current[currentIdxRef.current]
    if (!cur?.video_id) return 'No track playing — play a song first.'
    const vEl2 = videoRef.current as unknown as HTMLMediaElement | null
    const aEl2 = audioRef.current as unknown as HTMLMediaElement | null
    const rawEl2 = (vEl2 && vEl2.currentTime > 0 ? vEl2.currentTime : 0) || (aEl2 && aEl2.currentTime > 0 ? aEl2.currentTime : 0)
    const t = Math.floor(rawEl2 > 0 ? rawEl2 : (currentTimeRef.current || 0))
    const url = `https://www.youtube.com/watch?v=${cur.video_id}` + (t > 1 ? `&t=${t}s` : '')
    const w = window.open(url, '_blank', 'noopener,noreferrer')
    if (!w) return `Popup blocked. Open manually: ${url}`
    return `Opened "${cur.title}" on YouTube at ${t}s: ${url}`
  }, [])

  const popoutVideo = useCallback((trackOverride?: MusicTrack | null): string => {
    const cur = (trackOverride && (trackOverride as MusicTrack).video_id ? (trackOverride as MusicTrack) : queueRef.current[currentIdxRef.current]) as MusicTrack | undefined
    if (!cur?.video_id) return 'No track playing — play a song first.'
    const title = (cur.title || 'Unknown').replace(/"/g, '&quot;')
    const stream = cur.stream_url || ''
    const thumb = cur.thumb || ''
    const vEl = videoRef.current as unknown as HTMLMediaElement | null
    const aEl = audioRef.current as unknown as HTMLMediaElement | null
    const rawElTime = (vEl && vEl.currentTime > 0 ? vEl.currentTime : 0) || (aEl && aEl.currentTime > 0 ? aEl.currentTime : 0)
    const rawRefTime = currentTimeRef.current
    const curTime = Math.floor(rawElTime > 0 ? rawElTime : rawRefTime || 0)
    const shouldPlay = isPlayingRef.current
    // multi-tab: unique id + channel per tab (allows independent open tabs)
    const tabId = `tab_${Date.now()}_${Math.random().toString(36).slice(2,5)}`
    const channelName = `mayday-popout-${tabId}`
    let bc: BroadcastChannel | null = null
    try { bc = new BroadcastChannel(channelName) } catch { bc = null }
    // legacy single-tab ref kept for cleanup on unmount
    if (bc) { bcRef.current = bc; popoutChannelsRef.current.set(tabId, bc) }
    let popoutWin: Window | null = null
    const safePostTab = (msg: any) => {
      let ok = false
      const ch = popoutChannelsRef.current.get(tabId) || bc
      if (ch) { try { ch.postMessage(msg); ok = true } catch {} }
      if (!ok && popoutWin && !popoutWin.closed) {
        try { popoutWin.postMessage({ ...msg, _tabId: tabId }, '*'); ok = true } catch {}
      }
      return ok
    }
    const isAudioCur = !!cur.is_audio_only || /mime=audio/i.test(stream)
    const getElForCur = (): HTMLMediaElement | null => (isAudioCur ? aEl : vEl) || getActiveEl()
    // per-tab message handler (updates that tab's lastTime/playing, and parent if same video)
    if (bc) {
      bc.onmessage = (e: MessageEvent) => {
        const d: any = e.data || {}
        // per-tab bookkeeping
        if (typeof d.t === 'number') popoutLastTimeRef.current.set(tabId, d.t)
        if (d.type === 'play') { popoutPlayingRef.current.set(tabId, true); try { fetch('/api/music/popouts/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ tab_id: tabId, is_playing: true })}).catch(()=>{}) } catch {} }
        if (d.type === 'pause') { popoutPlayingRef.current.set(tabId, false); try { fetch('/api/music/popouts/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ tab_id: tabId, is_playing: false })}).catch(()=>{}) } catch {} }
        // reflect in UI list
        setOpenPopouts(prev => prev.map(t => t.id === tabId ? { ...t, isPlaying: d.type === 'play' ? true : d.type === 'pause' ? false : t.isPlaying } : t))
        // also sync parent media if this tab matches the current queue track (same videoId) — keeps legacy single-tab sync behavior for current song
        const isCurrentVideo = queueRef.current[currentIdxRef.current]?.video_id === cur.video_id
        if (!isCurrentVideo) return
        const el = getElForCur()
        if (!el) return
        if (d.type === 'seek' && typeof d.t === 'number') { el.currentTime = d.t; setCurrentTime(d.t) }
        if (d.type === 'play') { el.play().catch(()=>{}); }
        if (d.type === 'pause') { el.pause() }
        if (d.type === 'timeupdate' && typeof d.t === 'number') { setCurrentTime(d.t) }
        if (d.type === 'error') { setPlayError(String(d.msg || 'Popout playback error')); setTimeout(()=>setPlayError(null), 5000) }
        if (d.type === 'stuck') { setPlayError('Popout stalled — retrying sync…'); setTimeout(()=>setPlayError(null), 3000) }
      }
    }
    const onWinMsgTab = (e: MessageEvent) => {
      if (!e.data || typeof e.data !== 'object') return
      const d: any = e.data
      if (d._tabId && d._tabId !== tabId) return
      if (bc) return // BC already handled for this tab
      if (!d.type) return
      if (typeof d.t === 'number') popoutLastTimeRef.current.set(tabId, d.t)
      if (d.type === 'play') { popoutPlayingRef.current.set(tabId, true); try { fetch('/api/music/popouts/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ tab_id: tabId, is_playing: true })}).catch(()=>{}) } catch {} }
      if (d.type === 'pause') { popoutPlayingRef.current.set(tabId, false); try { fetch('/api/music/popouts/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ tab_id: tabId, is_playing: false })}).catch(()=>{}) } catch {} }
      setOpenPopouts(prev => prev.map(t => t.id === tabId ? { ...t, isPlaying: d.type === 'play' ? true : d.type === 'pause' ? false : t.isPlaying } : t))
      const isCurrentVideo = queueRef.current[currentIdxRef.current]?.video_id === cur.video_id
      if (!isCurrentVideo) return
      const el = getElForCur()
      if (!el) return
      if (d.type === 'seek' && typeof d.t === 'number') { el.currentTime = d.t; setCurrentTime(d.t) }
      if (d.type === 'play') el.play().catch(()=>{})
      if (d.type === 'pause') el.pause()
      if (d.type === 'timeupdate' && typeof d.t === 'number') { setCurrentTime(d.t) }
    }
    window.addEventListener('message', onWinMsgTab)
    // parent -> tab forwarding is now per-tab explicit via toggleTabPlay/focus; no auto broadcast of parent seeks to all tabs (each tab independent)
    const cleanupParentListeners = () => {
      window.removeEventListener('message', onWinMsgTab)
    }
    // close detection per tab + independent resume (tabs are independent; resume only if this tab was playing and matches current video)
    let closedCheck: number | null = null
    const startClosedCheck = (w: Window) => {
      popoutWin = w
      popoutWindowsRef.current.set(tabId, w)
      closedCheck = window.setInterval(() => {
        if (w.closed) {
          if (closedCheck) clearInterval(closedCheck)
          cleanupParentListeners()
          const ch = popoutChannelsRef.current.get(tabId)
          try { ch?.close() } catch {}
          popoutChannelsRef.current.delete(tabId)
          popoutWindowsRef.current.delete(tabId)
          popoutLastTimeRef.current.delete(tabId)
          popoutPlayingRef.current.delete(tabId)
          setOpenPopouts(prev => prev.filter(t => t.id !== tabId))
          try { fetch(`/api/music/popouts/${encodeURIComponent(tabId)}`, { method:'DELETE'}).catch(()=>{}) } catch {}
          if (bcRef.current === ch) bcRef.current = null
          const isCurrentVideo = queueRef.current[currentIdxRef.current]?.video_id === cur.video_id
          if (isCurrentVideo && shouldPlay) {
            const el = getElForCur()
            const last = popoutLastTimeRef.current.get(tabId) ?? curTime
            if (el) {
              try { el.currentTime = last } catch {}
              setTimeout(()=> { el.play().catch(()=> setNeedsGesture(true)) }, 120)
            }
          }
        }
      }, 900) as unknown as number
    }

    // Always use real YouTube video in popup — ytmusic album art not shown (per user request);
    // architecture unchanged: still same MusicTrack/store, only popout mediaHtml changes to iframe-first
    const iframeSrc = `https://www.youtube.com/embed/${cur.video_id}?autoplay=1&start=${curTime}&rel=0&enablejsapi=1&origin=${encodeURIComponent(window.location.origin)}`
    const iframeHtml = `<iframe id="mframe" width="640" height="360" src="${iframeSrc}" frameborder="0" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen style="width:100%;aspect-ratio:16/9;background:#000"></iframe>`
    let fallbackHtml = ''
    if (stream) {
      const isAudioFallback = !!cur.is_audio_only || /mime=audio/i.test(stream)
      const posterAttr = thumb ? ` poster="${thumb}"` : ''
      if (isAudioFallback) {
        fallbackHtml = `<audio id="mvideo" controls preload="auto" src="${stream}" style="width:100%;display:none" muted></audio>`
      } else {
        fallbackHtml = `<video id="mvideo" controls playsinline preload="auto"${posterAttr} src="${stream}" style="width:100%;aspect-ratio:16/9;background:#000;display:none" muted></video>`
      }
    }
    const mediaHtml = iframeHtml + fallbackHtml + `<p id="mstatus" style="color:#22c55e;font-size:11px;text-align:center;margin:4px 0 0">${shouldPlay ? `Playing YouTube at ${curTime}s…` : `Paused at ${curTime}s`}</p>`
    const syncScript = `
<script>
  (function(){
    let bc = null;
    try { bc = new BroadcastChannel('${channelName}'); } catch(e) { bc = null; }
    const tabId = "${tabId}";
    const v = document.getElementById('mvideo');
    const frame = document.getElementById('mframe');
    const mstatus = document.getElementById('mstatus');
    const startTime = ${curTime};
    const shouldPlay = ${shouldPlay ? 'true' : 'false'};
    const videoId = "${cur.video_id}";
    const setStatus = (t)=>{ if(mstatus) mstatus.textContent = t; };
    const safePost = (msg)=>{
      let ok=false;
      const withId = Object.assign({}, msg, {_tabId: tabId});
      if(bc){ try{ bc.postMessage(withId); ok=true; }catch(e){} }
      if(!ok && window.opener){ try{ window.opener.postMessage(withId,'*'); ok=true; }catch(e){} }
      return ok;
    };
    const ytCmd = (func, args)=>{
      if(!frame || !frame.contentWindow) return;
      try{ frame.contentWindow.postMessage(JSON.stringify({event:'command', func:func, args:args||[]}), '*'); }catch(e){}
    };
    let lastSeekSent = -1;
    let openAt = Date.now();
    let baseTime = startTime;
    const onParentMsg = (e)=>{
      const d = e.data || {};
      if(d._tabId && d._tabId !== tabId) return;
      if(!d.type) return;
      if(['seek','play','pause','close'].indexOf(d.type)===-1) return;
      try{
        if(d.type==='seek' && typeof d.t==='number'){
          baseTime = d.t; openAt = Date.now();
          if(frame) ytCmd('seekTo',[d.t, true]);
          if(v && v.style.display!=='none' && Math.abs(v.currentTime - d.t) > 0.4) v.currentTime = d.t;
          setStatus('Seeked to ' + Math.floor(d.t) + 's');
        }
        if(d.type==='play'){ if(frame) ytCmd('playVideo'); if(v && v.style.display!=='none') v.play().catch(()=>{}); setStatus('Playing YouTube — ' + Math.floor(baseTime) + 's'); }
        if(d.type==='pause'){ if(frame) ytCmd('pauseVideo'); if(v && v.style.display!=='none') v.pause(); setStatus('Paused at ' + Math.floor(baseTime) + 's'); }
      }catch(e){}
    };
    if(bc) bc.onmessage = onParentMsg;
    window.addEventListener('message', (ev)=>{ if(bc) return; onParentMsg(ev); });
    if(frame){
      setStatus(shouldPlay ? 'Playing YouTube at ' + startTime + 's' : 'Paused at ' + startTime + 's');
      let iframeErrFired=false;
      const fallbackToStream = ()=>{
        if(iframeErrFired) return; iframeErrFired=true;
        if(v){
          try{
            frame.style.display='none';
            v.style.display='';
            const approx = baseTime + Math.floor((Date.now()-openAt)/1000);
            if(v.readyState>=1) { if(Math.abs(v.currentTime-approx)>0.4) v.currentTime = approx; }
            if(shouldPlay) v.play().catch(()=>{});
            setTimeout(()=>{try{v.muted=false}catch(e){}},600);
            setStatus('YouTube blocked — playing fallback stream at ' + approx + 's');
          }catch(e){}
        } else {
          setStatus('YouTube failed to load — open on YouTube');
          safePost({type:'error', msg:'YouTube iframe failed'});
        }
      };
      frame.addEventListener('error', fallbackToStream);
      setTimeout(()=>{ if(!iframeErrFired && frame){ } }, 7000);
      if(shouldPlay){
        setInterval(()=>{
          const approx = baseTime + (Date.now()-openAt)/1000;
          safePost({type:'timeupdate', t: approx});
        }, 900);
      }
    }
    if(v){
      let ignore2=false;
      const doSync = ()=>{
        try{
          if(v.style.display==='none') return;
          if(v.readyState>=1 && Math.abs(v.currentTime-startTime)>0.4) v.currentTime=startTime;
          if(shouldPlay) v.play().catch(()=>{});
          setTimeout(()=>{try{v.muted=false}catch(e){}},600);
        }catch(e){}
      };
      if(v.style.display!=='none'){
        if(v.readyState>=1) doSync(); else v.addEventListener('loadedmetadata', doSync, {once:true});
        v.addEventListener('error', ()=>{
          setStatus('Fallback stream failed — open on YouTube');
          safePost({type:'error', msg:'Fallback failed'});
        });
        v.addEventListener('play', ()=>{ if(!ignore2) safePost({type:'play'}); });
        v.addEventListener('pause', ()=>{ if(!ignore2) safePost({type:'pause'}); });
        v.addEventListener('seeked', ()=>{ if(Math.abs(v.currentTime-lastSeekSent)<0.3) return; lastSeekSent=v.currentTime; safePost({type:'seek', t:v.currentTime}); });
        let lastSent=0; v.addEventListener('timeupdate', ()=>{ if(Date.now()-lastSent>700){lastSent=Date.now(); safePost({type:'timeupdate', t:v.currentTime});} });
      }
      const origOnParentMsg = onParentMsg;
      const wrapped = (e)=>{
        origOnParentMsg(e);
        const d=e.data||{}; if(v.style.display!=='none'){
          ignore2=true;
          try{ if(d.type==='seek' && typeof d.t==='number' && Math.abs(v.currentTime-d.t)>0.4) v.currentTime=d.t; if(d.type==='play') v.play().catch(()=>{}); if(d.type==='pause') v.pause(); }catch(e){}
          setTimeout(()=> ignore2=false,280);
        }
      };
      if(bc) bc.onmessage = wrapped;
      else { window.removeEventListener('message', onParentMsg as any); window.addEventListener('message', (ev)=> wrapped(ev)); }
    }
    window.addEventListener('beforeunload', ()=>{ try{ safePost({type:'close'}); if(bc) bc.close(); }catch(e){} });
    window.addEventListener('pagehide', ()=>{ try{ safePost({type:'close'}); }catch(e){} });
    safePost({type:'hello', t:startTime});
  })();
<\/script>`
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>${title} — Mayday</title><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0;background:#050505;color:#e5e5e5;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;display:flex;flex-direction:column;min-height:100vh}header{padding:12px 16px;border-bottom:1px solid #222;display:flex;justify-content:space-between;align-items:center}h1{margin:0;font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}main{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px;gap:12px}small{color:#888}</style></head><body><header><h1 title="${title}">${title} — ${cur.artist}</h1><small>${(cur.language||'').toUpperCase()} · YouTube · ${curTime}s ${shouldPlay ? '▶' : '⏸'} · ${tabId}</small></header><main>${mediaHtml}<small>${cur.artist} · ${cur.duration || ''} ${shouldPlay ? '▶ playing' : '⏸ paused'} — YouTube sync</small></main>${syncScript}</body></html>`
    const w = window.open('', 'maydayPopout_' + tabId, 'width=720,height=520,resizable=yes,scrollbars=yes')
    if (!w) {
      cleanupParentListeners()
      try { bc?.close() } catch {}
      popoutChannelsRef.current.delete(tabId)
      setOpenPopouts(prev => prev.filter(t => t.id !== tabId))
      const fallback = `https://www.youtube.com/watch?v=${cur.video_id}` + (curTime>1?`&t=${curTime}s`:'')
      const ww = window.open(fallback, '_blank')
      if (!ww) return `Popup blocked. Open manually: ${fallback}`
      return `Popup blocked for custom window, opened YouTube at ${curTime}s: ${fallback}`
    }
    try {
      w.document.open()
      w.document.write(html)
      w.document.close()
      w.focus()
      // register tab for manager (must be after successful open)
      setOpenPopouts(prev => {
        if (prev.some(t => t.id === tabId)) return prev
        return [...prev, { id: tabId, videoId: cur.video_id, title: cur.title || 'Unknown', artist: cur.artist || '', thumb: cur.thumb || '', duration: cur.duration || '', startTime: curTime, isPlaying: shouldPlay }]
      })
      // sync to backend registry for LLM list_popout_tabs
      try { fetch('/api/music/popouts/register', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ tab_id: tabId, video_id: cur.video_id, title: cur.title, artist: cur.artist, thumb: cur.thumb, duration: cur.duration, is_playing: shouldPlay, start_time: curTime })}).catch(()=>{}) } catch {}
      startClosedCheck(w)
    } catch (e: any) {
      cleanupParentListeners()
      try { w.close() } catch {}
      try { bc?.close() } catch {}
      popoutChannelsRef.current.delete(tabId)
      setOpenPopouts(prev => prev.filter(t => t.id !== tabId))
      const fallback = `https://www.youtube.com/watch?v=${cur.video_id}` + (curTime>1?`&t=${curTime}s`:'')
      window.open(fallback, '_blank')
      return `Popout failed (${e?.message}), opened YouTube at ${curTime}s: ${fallback}`
    }
    return `Popped out "${cur.title}" in new tab ${tabId} at ${curTime}s — open tabs: ${popoutWindowsRef.current.size + 1}`
  }, [])

  const closeTab = useCallback((id: string) => {
    const w = popoutWindowsRef.current.get(id)
    const ch = popoutChannelsRef.current.get(id)
    try { ch?.close() } catch {}
    try { if (w && !w.closed) w.close() } catch {}
    popoutWindowsRef.current.delete(id)
    popoutChannelsRef.current.delete(id)
    popoutLastTimeRef.current.delete(id)
    popoutPlayingRef.current.delete(id)
    setOpenPopouts(prev => prev.filter(t => t.id !== id))
    try { fetch(`/api/music/popouts/${encodeURIComponent(id)}`, { method:'DELETE'}).catch(()=>{}) } catch {}
  }, [])

  const focusTab = useCallback((id: string) => {
    const w = popoutWindowsRef.current.get(id)
    if (w && !w.closed) { try { w.focus() } catch {} return }
    setPlayError(`Tab ${id} is closed`)
    setTimeout(()=> setPlayError(null), 3000)
  }, [])

  const toggleTabPlay = useCallback((id: string, explicitIsPlaying?: boolean) => {
    const ch = popoutChannelsRef.current.get(id)
    const w = popoutWindowsRef.current.get(id)
    const isPlaying = popoutPlayingRef.current.get(id)
    if (!ch && !w) { setPlayError(`Tab ${id} not found`); setTimeout(()=>setPlayError(null), 3000); return }
    const targetPlaying = explicitIsPlaying !== undefined ? explicitIsPlaying : !isPlaying
    const nextType = targetPlaying ? 'play' : 'pause'
    // if already in target state, no-op
    if (explicitIsPlaying !== undefined && isPlaying === explicitIsPlaying) return
    let ok = false
    if (ch) { try { ch.postMessage({ type: nextType, _tabId: id }); ok = true } catch {} }
    if (!ok && w && !w.closed) { try { w.postMessage({ type: nextType, _tabId: id }, '*'); ok = true } catch {} }
    if (ok) {
      popoutPlayingRef.current.set(id, targetPlaying)
      setOpenPopouts(prev => prev.map(t => t.id === id ? { ...t, isPlaying: targetPlaying } : t))
      // also sync backend registry for LLM list view
      try { fetch('/api/music/popouts/update', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ tab_id: id, is_playing: targetPlaying })}).catch(()=>{}) } catch {}
    }
  }, [])

  // global cleanup: close all popout channels/windows on unmount
  useEffect(() => () => {
    for (const ch of popoutChannelsRef.current.values()) { try { ch.close() } catch {} }
    for (const w of popoutWindowsRef.current.values()) { try { if (!w.closed) w.close() } catch {} }
    popoutChannelsRef.current.clear()
    popoutWindowsRef.current.clear()
  }, [])

  const handleMusicMessage = useCallback((data: any) => {
    if (!data || data.type !== 'music') return
    const action = data.action || 'play'
    const track: MusicTrack | null = data.track || null
    const q: MusicTrack[] = Array.isArray(data.queue) ? data.queue : []
    if (action === 'ended') return
    if (action === 'open_popup' || action === 'open_youtube' || action === 'popout') {
      // LLM-triggered open — supports multi-tab: specific track opens in its own new tab
      setTimeout(() => {
        if (track?.video_id) {
          // multi-tab: open this video in a new YouTube popup tab (real video, not album)
          const t: MusicTrack = {
            video_id: track.video_id,
            title: (track as any).title || track.video_id,
            artist: (track as any).artist || (track as any).channel || 'Unknown',
            thumb: (track as any).thumb || '',
            duration: (track as any).duration || '',
            language: (track as any).language || 'other',
            stream_url: (track as any).stream_url || '',
            is_audio_only: (track as any).is_audio_only,
          } as MusicTrack
          const res = action === 'open_youtube' ? (()=>{ const url=`https://www.youtube.com/watch?v=${t.video_id}`; const w=window.open(url,'_blank','noopener,noreferrer'); return w?`Opened ${t.title} on YouTube`: `Popup blocked. Open manually: ${url}` })() : popoutVideo(t)
          if (res.startsWith('Popup blocked') || res.startsWith('No track')) {
            setPlayError(res)
            setTimeout(() => setPlayError(null), 6000)
          }
          return
        }
        const res = action === 'open_youtube' ? openYouTube() : popoutVideo(null)
        if (res.startsWith('Popup blocked') || res.startsWith('No track')) {
          setPlayError(res)
          setTimeout(() => setPlayError(null), 6000)
        }
      }, 100)
      return
    }
    if (action === 'popout_close' && (data as any).tab_id) { closeTab((data as any).tab_id); return }
    if (action === 'popout_focus' && (data as any).tab_id) { focusTab((data as any).tab_id); return }
    if (action === 'popout_toggle' && (data as any).tab_id) { toggleTabPlay((data as any).tab_id, (data as any).is_playing); return }
    if ((data as any).tab_id && (action === 'pause' || action === 'play') && (data as any).tab_id) {
      // legacy fallback: treat as toggle if tab_id present but action is generic
    }
    // Songs-only bottom bar per user: YouTube/tutorial video tracks go to popup windows, never the PlayerBar queue
    const _isVideo = !!(track as any)?.kind && (track as any).kind === 'video'
    if (_isVideo && track) {
      setTimeout(() => {
        const t: MusicTrack = {
          video_id: track.video_id,
          title: (track as any).title || track.video_id,
          artist: (track as any).artist || (track as any).channel || 'Unknown',
          thumb: (track as any).thumb || '',
          duration: (track as any).duration || '',
          language: (track as any).language || 'other',
          stream_url: (track as any).stream_url || '',
          is_audio_only: (track as any).is_audio_only,
          kind: 'video',
        } as MusicTrack
        const res = popoutVideo(t)
        if (res.startsWith('Popup blocked') || res.startsWith('No track')) {
          setPlayError(res)
          setTimeout(() => setPlayError(null), 6000)
        }
      }, 100)
      return
    }
    if (action === 'queue' && track) {
      // refuse to queue video tracks into songs bar — open as popup tab instead
      if (_isVideo) {
        const t2: MusicTrack = { video_id: track.video_id, title: (track as any).title || track.video_id, artist: (track as any).artist || 'Unknown', thumb: (track as any).thumb || '', duration: (track as any).duration || '', language: (track as any).language || 'other', stream_url: (track as any).stream_url || '', is_audio_only: (track as any).is_audio_only, kind: 'video' } as MusicTrack
        setTimeout(() => popoutVideo(t2), 100)
        return
      }
      setQueue(prev => [...prev, track]); return
    }
    if ((action === 'play' || action === 'playing') && track) {
      // queue may contain mixed kinds from backend — strip video tracks from the bar queue
      const filteredQ = q.filter((x:any) => (x as any)?.kind !== 'video')
      setResolving(false); setPlayError(null); setNeedsGesture(false)
      const newQueue = [track, ...filteredQ]
      // store genre context for auto-queue continuity
      lastContextRef.current = {
        mood: (track as any).mood_id || (track as any).mood || (track as any).genre || '',
        genre: (track as any).genre || (track as any).mood || '',
        language: track.language || '',
        seedVideoId: track.video_id || '',
      }
      try { localStorage.setItem('mayday_last_music_context', JSON.stringify(lastContextRef.current)) } catch {}
      setQueue(newQueue); setCurrentIdx(0); return
    }
    if (action === 'pause') setIsPlaying(false)
    if (action === 'resume') play()
  }, [play, openYouTube, popoutVideo, closeTab, focusTab, toggleTabPlay])

  // hydrate lastContext from localStorage once
  useEffect(() => {
    try {
      const raw = localStorage.getItem('mayday_last_music_context')
      if (raw) lastContextRef.current = JSON.parse(raw)
    } catch {}
  }, [])

  return {
    queue, current, currentIdx, isPlaying, currentTime, duration, volume, repeat, autoPlay, expanded, needsGesture, playError, resolving, openPopouts,
    setExpanded, play, pause, next, prev, seek, setVolume: setVolume, toggleRepeat, toggleAutoPlay, jumpTo, clearQueue,
    handleMusicMessage, videoRef, audioRef, openYouTube, popoutVideo, closeTab, focusTab, toggleTabPlay,
  }
}
