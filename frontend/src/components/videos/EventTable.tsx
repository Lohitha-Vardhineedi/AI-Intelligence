"use client";

import { useState } from "react";

import { ErrorMessage } from "@/components/ui/Alert";
import { SeverityBadge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Pagination } from "@/components/ui/Pagination";
import { apiUrl } from "@/lib/config";
import { errorMessage } from "@/lib/errors";
import { formatVideoTime, humanize } from "@/lib/format";
import { useGetEventsQuery } from "@/services/videosApi";

const PAGE_SIZE = 25;

interface EventTableProps {
  jobId: string;
  eventCounts: Record<string, number>;
  onSeek: (seconds: number) => void;
}

export function EventTable({ jobId, eventCounts, onSeek }: EventTableProps) {
  const [eventType, setEventType] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, isFetching } = useGetEventsQuery({
    jobId,
    eventType,
    page,
    pageSize: PAGE_SIZE,
  });

  const filter = (
    <label className="flex items-center gap-2 text-sm text-slate-400">
      Show
      <select
        value={eventType}
        onChange={(event) => {
          setEventType(event.target.value);
          setPage(1);
        }}
        className="rounded-md border border-slate-700 bg-slate-800 px-2 py-1 text-slate-100"
      >
        <option value="">All events</option>
        {Object.entries(eventCounts).map(([type, count]) => (
          <option key={type} value={type}>
            {humanize(type)} ({count})
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <Card title="Events" actions={filter}>
      {error ? (
        <ErrorMessage>{errorMessage(error)}</ErrorMessage>
      ) : (
        <div className={`space-y-4 ${isFetching ? "opacity-60" : ""}`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th scope="col" className="py-2 pr-4 font-medium">Time</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Event</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Severity</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Track</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Where</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Confidence</th>
                  <th scope="col" className="py-2 font-medium">Snapshot</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {data?.items.map((event) => {
                  const seconds = event.video_timestamp_ms / 1000;
                  return (
                    <tr key={event.id}>
                      <td className="py-2 pr-4">
                        <button
                          type="button"
                          onClick={() => onSeek(seconds)}
                          className="font-mono text-sky-400 hover:underline"
                          aria-label={`Play from ${formatVideoTime(seconds)}`}
                        >
                          {formatVideoTime(seconds)}
                        </button>
                      </td>
                      <td className="py-2 pr-4 text-slate-100">{event.title}</td>
                      <td className="py-2 pr-4">
                        <SeverityBadge severity={event.severity} />
                      </td>
                      <td className="py-2 pr-4 text-slate-300">
                        {event.track_id !== null ? `#${event.track_id}` : "—"}
                      </td>
                      <td className="py-2 pr-4 text-slate-300">
                        {event.zone_name ?? event.line_name ?? "—"}
                      </td>
                      <td className="py-2 pr-4 text-slate-300">
                        {event.confidence !== null ? `${Math.round(event.confidence * 100)}%` : "—"}
                      </td>
                      <td className="py-2">
                        {event.has_snapshot ? (
                          <a
                            href={apiUrl(`/events/${event.id}/snapshot`)}
                            target="_blank"
                            rel="noreferrer"
                            className="text-sky-400 hover:underline"
                          >
                            View
                          </a>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {data && (
            <Pagination pagination={data.pagination} onPageChange={setPage} label="Event pages" />
          )}
        </div>
      )}
    </Card>
  );
}
