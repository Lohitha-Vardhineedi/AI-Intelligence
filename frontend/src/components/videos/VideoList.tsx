"use client";

import Link from "next/link";
import { useState } from "react";

import { ErrorMessage } from "@/components/ui/Alert";
import { JobStatusBadge } from "@/components/ui/Badge";
import { Pagination } from "@/components/ui/Pagination";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { errorMessage } from "@/lib/errors";
import { formatBytes, formatDateTime, formatDuration } from "@/lib/format";
import { useGetVideosQuery, videosApi } from "@/services/videosApi";
import { isJobActive, type Video } from "@/types/video";

import { AddVideoButton } from "./AddVideoButton";

const PAGE_SIZE = 20;

function JobCell({ video }: { video: Video }) {
  const job = video.latest_job;
  if (job?.status === "PROCESSING") {
    return (
      <div className="w-32 space-y-1">
        <ProgressBar value={job.progress_percent} label={`Analysing ${video.filename}`} />
        <span className="text-xs text-slate-400">{Math.round(job.progress_percent)}%</span>
      </div>
    );
  }
  return <JobStatusBadge status={job?.status ?? null} />;
}

function ResultCell({ video }: { video: Video }) {
  const summary = video.latest_job?.status === "COMPLETED" ? video.latest_job.summary : null;
  if (!summary) return <span className="text-slate-500">—</span>;
  return (
    <span>
      {summary.unique_counts.person ?? 0} people · {summary.alerts.length} alert
      {summary.alerts.length === 1 ? "" : "s"}
    </span>
  );
}

export function VideoList() {
  const [page, setPage] = useState(1);
  const args = { page, pageSize: PAGE_SIZE };
  // Keep refreshing while any video on this page is still being analysed.
  const { data: cached } = videosApi.endpoints.getVideos.useQueryState(args);
  const anyActive = cached?.items.some((video) => isJobActive(video.latest_job)) ?? false;
  const { data, error, isLoading } = useGetVideosQuery(args, {
    pollingInterval: anyActive ? 2000 : 0,
  });

  if (isLoading) return <p className="text-sm text-slate-400">Loading videos…</p>;
  if (error) return <ErrorMessage>{errorMessage(error)}</ErrorMessage>;
  if (!data || data.items.length === 0) {
    return (
      <div className="flex flex-col items-center gap-4 rounded-lg border border-dashed border-slate-700 px-6 py-16 text-center">
        <p className="text-slate-300">No videos yet.</p>
        <p className="max-w-md text-sm text-slate-400">
          Upload a recording to count people and objects, follow each one with a track ID
          and find line crossings and restricted-zone entries.
        </p>
        <AddVideoButton />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-900 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium">Video</th>
              <th scope="col" className="px-4 py-3 font-medium">Length</th>
              <th scope="col" className="px-4 py-3 font-medium">Resolution</th>
              <th scope="col" className="px-4 py-3 font-medium">Size</th>
              <th scope="col" className="px-4 py-3 font-medium">Uploaded</th>
              <th scope="col" className="px-4 py-3 font-medium">Status</th>
              <th scope="col" className="px-4 py-3 font-medium">Result</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {data.items.map((video) => (
              <tr key={video.id} className="hover:bg-slate-900/60">
                <td className="max-w-xs truncate px-4 py-3">
                  <Link href={`/videos/${video.id}`} className="font-medium text-sky-300 hover:underline">
                    {video.filename}
                  </Link>
                </td>
                <td className="px-4 py-3 text-slate-300">{formatDuration(video.duration_seconds)}</td>
                <td className="px-4 py-3 text-slate-300">
                  {video.width}×{video.height}
                </td>
                <td className="px-4 py-3 text-slate-300">{formatBytes(video.size_bytes)}</td>
                <td className="px-4 py-3 text-slate-300">{formatDateTime(video.created_at)}</td>
                <td className="px-4 py-3">
                  <JobCell video={video} />
                </td>
                <td className="px-4 py-3 text-slate-300">
                  <ResultCell video={video} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Pagination pagination={data.pagination} onPageChange={setPage} label="Video pages" />
    </div>
  );
}
