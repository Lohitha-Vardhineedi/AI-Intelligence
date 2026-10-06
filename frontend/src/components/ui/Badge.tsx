import type { JobStatus, Severity } from "@/types/video";

const BASE = "inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold";

// Severity colours are used for severity only: red, orange, amber, blue, grey.
const SEVERITY: Record<Severity, string> = {
  CRITICAL: "bg-red-500/15 text-red-300 ring-1 ring-red-500/40",
  HIGH: "bg-orange-500/15 text-orange-300 ring-1 ring-orange-500/40",
  MEDIUM: "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/40",
  LOW: "bg-blue-500/15 text-blue-300 ring-1 ring-blue-500/40",
  INFO: "bg-slate-500/15 text-slate-300 ring-1 ring-slate-500/40",
};

const STATUS: Record<JobStatus, { label: string; className: string }> = {
  QUEUED: { label: "Queued", className: "bg-slate-700 text-slate-200" },
  PROCESSING: { label: "Processing", className: "bg-sky-500/20 text-sky-300" },
  COMPLETED: { label: "Completed", className: "bg-emerald-500/20 text-emerald-300" },
  FAILED: { label: "Failed", className: "bg-red-500/20 text-red-300" },
  CANCELLED: { label: "Cancelled", className: "bg-slate-700 text-slate-300" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`${BASE} ${SEVERITY[severity]}`}>{severity}</span>;
}

export function JobStatusBadge({ status }: { status: JobStatus | null }) {
  if (status === null) return <span className={`${BASE} bg-slate-800 text-slate-400`}>Not analysed</span>;
  const { label, className } = STATUS[status];
  return <span className={`${BASE} ${className}`}>{label}</span>;
}
