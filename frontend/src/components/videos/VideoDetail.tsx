"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { ErrorMessage } from "@/components/ui/Alert";
import { JobStatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { errorMessage } from "@/lib/errors";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/format";
import {
  useCancelJobMutation,
  useDeleteVideoMutation,
  useGetVideoQuery,
  useProcessVideoMutation,
  videosApi,
} from "@/services/videosApi";
import { isJobActive, type Job } from "@/types/video";

import { JobProgress } from "./JobProgress";
import { VideoResults } from "./VideoResults";

function JobNotice({ job }: { job: Job }) {
  if (job.status === "FAILED") {
    return <ErrorMessage>Analysis failed: {job.error_message ?? "unknown error"}</ErrorMessage>;
  }
  if (job.status === "CANCELLED") {
    return (
      <p className="rounded-md border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-300">
        Analysis was cancelled
        {job.summary ? `. Results below cover the first ${Math.round(job.summary.stream_seconds)} s.` : "."}
      </p>
    );
  }
  return null;
}

export function VideoDetail({ id }: { id: string }) {
  const router = useRouter();
  // Poll every second while the video is queued or being analysed.
  const { data: cached } = videosApi.endpoints.getVideo.useQueryState(id);
  const { data: video, error, isLoading } = useGetVideoQuery(id, {
    pollingInterval: isJobActive(cached?.latest_job) ? 1000 : 0,
  });
  const [processVideo, processing] = useProcessVideoMutation();
  const [cancelJob, cancelling] = useCancelJobMutation();
  const [deleteVideo, deleting] = useDeleteVideoMutation();

  if (isLoading) return <p className="text-sm text-slate-400">Loading…</p>;
  if (error || !video) {
    return (
      <div className="space-y-4">
        <ErrorMessage>{errorMessage(error)}</ErrorMessage>
        <Link href="/videos" className="text-sm text-sky-400 hover:underline">
          Back to all videos
        </Link>
      </div>
    );
  }

  const job = video.latest_job;
  const active = isJobActive(job);
  const actionError = processing.error ?? cancelling.error ?? deleting.error;

  const onDelete = async () => {
    if (!window.confirm(`Delete "${video.filename}" and its results? This can't be undone.`)) return;
    try {
      await deleteVideo(video.id).unwrap();
      router.push("/videos");
    } catch {
      // shown through `deleting.error`
    }
  };

  return (
    <div className="space-y-6">
      <Link href="/videos" className="text-sm text-slate-400 hover:text-slate-200">
        ← All videos
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="truncate text-2xl font-semibold" title={video.filename}>
              {video.filename}
            </h1>
            <JobStatusBadge status={job?.status ?? null} />
          </div>
          <p className="text-sm text-slate-400">
            {formatDuration(video.duration_seconds)} · {video.width}×{video.height} ·{" "}
            {video.fps.toFixed(1)} fps · {formatBytes(video.size_bytes)} · uploaded{" "}
            {formatDateTime(video.created_at)}
          </p>
        </div>
        <div className="flex gap-3">
          {active && job ? (
            <Button
              variant="secondary"
              onClick={() => cancelJob({ jobId: job.id, videoId: video.id })}
              disabled={job.cancel_requested || cancelling.isLoading}
            >
              {job.cancel_requested ? "Stopping…" : "Cancel analysis"}
            </Button>
          ) : (
            <Button onClick={() => processVideo(video.id)} disabled={processing.isLoading}>
              {job ? "Analyse again" : "Analyse"}
            </Button>
          )}
          <Button variant="danger" onClick={onDelete} disabled={active || deleting.isLoading}>
            Delete
          </Button>
        </div>
      </div>

      {actionError && <ErrorMessage>{errorMessage(actionError)}</ErrorMessage>}

      {!job && (
        <Card>
          <p className="text-sm text-slate-300">This video hasn&apos;t been analysed yet.</p>
        </Card>
      )}
      {job && active && <JobProgress job={job} />}
      {job && !active && (
        <>
          <JobNotice job={job} />
          <VideoResults key={job.id} video={video} job={job} />
        </>
      )}
    </div>
  );
}
