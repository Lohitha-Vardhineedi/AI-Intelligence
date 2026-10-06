export type JobStatus = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";

export type Severity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface AlertSummary {
  alert_id: string;
  rule_name: string;
  severity: Severity;
  title: string;
  event_id: string;
  event_type: string;
  track_id: number | null;
  zone_name: string | null;
  stream_time_s: number;
  occurrence_count: number;
}

export interface NotificationRecord {
  alert_id: string;
  provider: string;
  to: string;
  status: "SENT" | "FAILED" | "SUPPRESSED";
  error: string | null;
}

export interface JobSummary {
  frames_read: number;
  frames_processed: number;
  stream_seconds: number;
  processing_seconds: number;
  unique_counts: Record<string, number>;
  peak_counts: Record<string, number>;
  line_counts: Record<string, { in: number; out: number }>;
  zone_counts: Record<string, { entries: number; exits: number }>;
  events_by_type: Record<string, number>;
  alerts: AlertSummary[];
  model: string;
  notifications: NotificationRecord[];
}

export interface Job {
  id: string;
  video_id: string;
  status: JobStatus;
  progress_percent: number;
  frames_processed: number;
  total_frames: number | null;
  processing_fps: number | null;
  cancel_requested: boolean;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  model_version: string | null;
  summary: JobSummary | null;
  has_annotated_video: boolean;
  created_at: string;
}

export interface Video {
  id: string;
  filename: string;
  size_bytes: number;
  format: string;
  duration_seconds: number;
  fps: number;
  width: number;
  height: number;
  frame_count: number;
  created_at: string;
  latest_job: Job | null;
}

export interface VideoEvent {
  id: string;
  job_id: string;
  event_type: string;
  severity: Severity;
  title: string;
  occurred_at: string;
  video_timestamp_ms: number;
  frame_index: number;
  track_id: number | null;
  object_class: string | null;
  confidence: number | null;
  zone_name: string | null;
  line_name: string | null;
  direction: string | null;
  has_snapshot: boolean;
}

export const isJobActive = (job: Job | null | undefined): boolean =>
  job?.status === "QUEUED" || job?.status === "PROCESSING";
