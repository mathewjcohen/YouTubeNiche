export type NicheStatus = 'candidate' | 'testing' | 'promoted' | 'archived'
export type GateState =
  | 'awaiting_review'
  | 'approved'
  | 'rejected'
  | 'auto_approved'
export type NicheSource = 'scout' | 'manual'

export interface BrandPackage {
  channel_name: string
  tagline: string
  primary_color: string
  font_pairing: string
  about_copy: string
  thumbnail_style: string
  tone: string
}

export interface Niche {
  id: string
  name: string
  category: string
  status: NicheStatus
  gate1_state: GateState
  niche_source: NicheSource
  score: number | null
  brand_package: BrandPackage | null
  activated_at: string | null
  created_at: string
}

export interface Topic {
  id: string
  niche_id: string
  title: string
  body: string
  reddit_post_id: string
  url: string
  claude_score: number | null
  gate2_state: GateState
  rejection_reason: string | null
  created_at: string
}

export interface Script {
  id: string
  topic_id: string
  niche_id: string
  long_form_text: string
  short_text: string
  youtube_title: string | null
  youtube_description: string | null
  youtube_tags: string[] | null
  gate3_state: GateState
  rejection_reason: string | null
  created_at: string
}

export interface Video {
  id: string
  script_id: string
  niche_id: string
  audio_path: string | null
  srt_path: string | null
  video_path: string | null
  thumbnail_path: string | null
  youtube_video_id: string | null
  gate4_state: GateState
  gate5_state: GateState
  gate6_state: GateState
  gate4_rejection_reason: string | null
  gate5_rejection_reason: string | null
  gate6_rejection_reason: string | null
  created_at: string
}

export interface GateConfig {
  id: string
  niche_id: string | null
  gate_number: number
  enabled: boolean
  updated_at: string
}

export interface NicheAnalytics {
  id: string
  niche_id: string
  polled_at: string
  views_total: number
  ctr: number
  avg_watch_time_pct: number
  subs_total: number
  early_promotion_flagged: boolean
}

export interface PendingCounts {
  gate1: number
  gate2: number
  gate3: number
  gate4: number
  gate5: number
  gate6: number
}
