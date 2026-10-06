"use client";

import { useRef, useState, type RefObject } from "react";

import { Card, StatCard } from "@/components/ui/Card";
import { apiUrl } from "@/lib/config";
import type { Job, JobSummary, Video } from "@/types/video";

import { AlertList } from "./AlertList";
import { EventTable } from "./EventTable";

function Stats({ summary }: { summary: JobSummary }) {
  const objects = Object.entries(summary.unique_counts).filter(([cls]) => cls !== "person");
  const smsSent = summary.notifications.filter((n) => n.status === "SENT").length;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
      <StatCard
        label="People"
        value={summary.unique_counts.person ?? 0}
        hint={`Up to ${summary.peak_counts.person ?? 0} at the same time`}
      />
      <StatCard
        label="Other objects"
        value={objects.reduce((sum, [, n]) => sum + n, 0)}
        hint={objects.map(([cls, n]) => `${cls} ${n}`).join(", ") || "None"}
      />
      {Object.entries(summary.line_counts).map(([name, counts]) => (
        <StatCard key={name} label={name} value={`${counts.in} in · ${counts.out} out`} />
      ))}
      {Object.entries(summary.zone_counts).map(([name, counts]) => (
        <StatCard
          key={name}
          label={name}
          value={`${counts.entries} entries`}
          hint={`${counts.exits} exits`}
        />
      ))}
      <StatCard label="Alerts" value={summary.alerts.length} hint={`${smsSent} SMS sent`} />
      <StatCard
        label="Processing time"
        value={`${Math.round(summary.processing_seconds)} s`}
        hint={`${summary.frames_processed} frames · ${summary.model}`}
      />
    </div>
  );
}

function Player({
  video,
  job,
  videoRef,
}: {
  video: Video;
  job: Job;
  videoRef: RefObject<HTMLVideoElement | null>;
}) {
  const [failed, setFailed] = useState(false);
  const original = apiUrl(`/videos/${video.id}/playback`);
  const src = job.has_annotated_video
    ? apiUrl(`/videos/${video.id}/annotated`)
    : video.format === "mp4"
      ? original
      : null;

  if (!src || failed) {
    return (
      <p className="text-sm text-slate-400">
        This browser can&apos;t play the video.{" "}
        <a href={src ?? original} className="text-sky-400 hover:underline" download>
          Download it
        </a>{" "}
        to watch it in a media player.
      </p>
    );
  }
  return (
    <video
      ref={videoRef}
      src={src}
      controls
      preload="metadata"
      onError={() => setFailed(true)}
      className="aspect-video w-full rounded-md bg-black"
    />
  );
}

export function VideoResults({ video, job }: { video: Video; job: Job }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const summary = job.summary;
  if (!summary) return null;

  const seek = (seconds: number) => {
    const player = videoRef.current;
    if (!player) return;
    player.currentTime = seconds;
    player.scrollIntoView({ behavior: "smooth", block: "center" });
    player.play().catch(() => {}); // autoplay can be blocked; the user can press play
  };

  return (
    <div className="space-y-6">
      <Stats summary={summary} />
      <Card title={job.has_annotated_video ? "Annotated video" : "Video"}>
        <Player video={video} job={job} videoRef={videoRef} />
      </Card>
      <AlertList alerts={summary.alerts} onSeek={seek} />
      <EventTable jobId={job.id} eventCounts={summary.events_by_type} onSeek={seek} />
    </div>
  );
}
