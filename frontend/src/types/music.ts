export interface MusicTrack {
  video_id: string
  title: string
  artist: string
  thumb: string
  duration: string
  language: string  // ta | hi | en | other
  stream_url: string
  is_audio_only?: boolean
  kind?: 'song' | 'video'
}

export interface MusicMessage {
  type: 'music'
  action: 'play' | 'queue' | 'playing' | 'ended' | 'pause' | 'resume'
  track: MusicTrack
  queue: MusicTrack[]
}

export interface HistoryStats {
  total_plays: number
  language_stats: Record<string, number>
  most_played_artists: { artist: string; plays: number }[]
  top_all: { video_id: string; title: string; artist: string; language: string; thumb: string; plays: number; last_played: string }[]
  top_week: { video_id: string; title: string; artist: string; language: string; thumb: string; plays: number; last_played: string }[]
}

export interface TrendingResponse {
  tracks: MusicTrack[]
  country: string
  biased_by?: string | null
  error?: string
}
