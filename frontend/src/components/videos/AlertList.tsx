"use client";

import Image from "next/image";
import { useState } from "react";

import { SeverityBadge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { apiUrl } from "@/lib/config";
import { formatVideoTime } from "@/lib/format";
import type { AlertSummary } from "@/types/video";

function Snapshot({ eventId, title }: { eventId: string; title: string }) {
  const [missing, setMissing] = useState(false);
  if (missing) return null;
  const src = apiUrl(`/events/${eventId}/snapshot`);
  return (
    <a href={src} target="_blank" rel="noreferrer" className="shrink-0">
      <Image
        src={src}
        alt={`Snapshot: ${title}`}
        width={160}
        height={90}
        unoptimized
        onError={() => setMissing(true)}
        className="h-[90px] w-40 rounded border border-slate-700 object-cover"
      />
    </a>
  );
}

export function AlertList({
  alerts,
  onSeek,
}: {
  alerts: AlertSummary[];
  onSeek: (seconds: number) => void;
}) {
  return (
    <Card title={`Alerts (${alerts.length})`}>
      {alerts.length === 0 ? (
        <p className="text-sm text-slate-400">No alert rules were triggered.</p>
      ) : (
        <ul className="divide-y divide-slate-800">
          {alerts.map((alert) => (
            <li key={alert.alert_id} className="flex items-start gap-4 py-3 first:pt-0 last:pb-0">
              <Snapshot eventId={alert.event_id} title={alert.title} />
              <div className="min-w-0 space-y-1 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={alert.severity} />
                  <span className="font-medium text-slate-100">{alert.title}</span>
                </div>
                <p className="text-slate-400">
                  {[alert.zone_name, alert.track_id !== null ? `track #${alert.track_id}` : null]
                    .filter(Boolean)
                    .join(" · ")}
                  {alert.occurrence_count > 1 &&
                    ` · ${alert.occurrence_count - 1} more within the cooldown`}
                </p>
                <p className="text-xs text-slate-500">Rule: {alert.rule_name}</p>
                <button
                  type="button"
                  onClick={() => onSeek(alert.stream_time_s)}
                  className="text-xs text-sky-400 hover:underline"
                >
                  Watch at {formatVideoTime(alert.stream_time_s)}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
