import { Card } from "@/components/ui/Card";
import { ProgressBar } from "@/components/ui/ProgressBar";
import type { Job } from "@/types/video";

export function JobProgress({ job }: { job: Job }) {
  const started = job.status === "PROCESSING" && job.frames_processed > 0;
  let message = "Waiting for a worker…";
  if (job.cancel_requested) message = "Stopping…";
  else if (job.status === "PROCESSING") message = started ? "Analysing video" : "Loading the AI model…";

  return (
    <Card title="Analysis in progress">
      <div className="space-y-3">
        <div className="flex items-baseline justify-between gap-4 text-sm">
          <span className="text-slate-200" aria-live="polite">
            {message}
          </span>
          {started && <span className="font-semibold text-slate-50">{Math.round(job.progress_percent)}%</span>}
        </div>
        <ProgressBar value={started ? job.progress_percent : null} label="Analysis progress" />
        {started && (
          <p className="text-xs text-slate-400">
            Frame {job.frames_processed.toLocaleString()}
            {job.total_frames ? ` of ${job.total_frames.toLocaleString()}` : ""}
            {job.processing_fps ? ` · ${job.processing_fps.toFixed(1)} frames per second analysed` : ""}
          </p>
        )}
      </div>
    </Card>
  );
}
