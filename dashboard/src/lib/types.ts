export type NicheStatus = 'candidate' | 'testing' | 'promoted' | 'archived'
export type GateState =
  | 'pending'
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

export type ChannelState = 'unconfigured' | 'linked'

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
  channel_state: ChannelState
  youtube_account_id: string | null
  youtube_accounts: { channel_name: string; channel_id: string | null } | null
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
  video_type: 'long' | 'short'
  status: string
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
  avg_view_duration_sec: number | null
  impressions: number
  long_views: number
  long_avg_view_duration_sec: number | null
  long_avg_watch_pct: number | null
  short_views: number
  short_avg_view_duration_sec: number | null
  short_avg_watch_pct: number | null
  subscribers_gained: number
  estimated_minutes_watched: number
  likes: number
  subs_total: number
  early_promotion_flagged: boolean
  videos_published: number
  shorts_published: number
}

export interface VideoAnalytics {
  id: string
  niche_id: string
  youtube_video_id: string
  video_type: 'long' | 'short'
  polled_at: string
  views: number
  avg_view_duration_sec: number | null
  avg_view_pct: number | null
  estimated_minutes_watched: number | null
  likes: number
}

export interface PendingCounts {
  gate1: number
  gate2: number
  gate3: number
  gate4: number
  gate5: number
  gate6: number
}

export interface VideoRecord {
  youtube_video_id: string
  niche_id: string
  niche_name: string
  video_type: 'long' | 'short'
  title: string
  duration_sec: number | null
  views: number
  avg_view_pct: number | null
  avg_view_duration_sec: number | null
  estimated_minutes_watched: number | null
  likes: number
  retention_50pct: number | null
}

interface VideoSummary {
  title: string
  niche: string
  type: string
  views: number
  watch_pct: number
  word_count: number
  duration_sec: number | null
}

export interface InsightStats {
  period_days: number
  total_videos: number
  total_views: number
  overall_avg_watch_pct: number
  by_niche: Array<{
    niche: string
    video_count: number
    total_views: number
    avg_watch_pct: number
    avg_views_per_video: number
  }>
  by_type: Record<string, {
    count: number
    total_views: number
    avg_watch_pct: number
    avg_views: number
  }>
  by_script_length: Array<{
    script_length: string
    count: number
    avg_watch_pct: number
    avg_views: number
  }>
  retention: {
    videos_with_data: number
    avg_50pct_dropoff: number | null
    median_50pct_dropoff: number | null
  }
  top_5_videos: VideoSummary[]
  bottom_5_videos: VideoSummary[]
}

export interface Insight {
  id: string
  generated_at: string
  period_days: number
  stats_json: InsightStats
  summary_text: string
}
