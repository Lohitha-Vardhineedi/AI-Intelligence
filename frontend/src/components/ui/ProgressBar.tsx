interface ProgressBarProps {
  value: number | null; // 0-100, or null while the amount of work is unknown
  label: string;
}

export function ProgressBar({ value, label }: ProgressBarProps) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value ?? undefined}
      className="h-2 w-full overflow-hidden rounded-full bg-slate-800"
    >
      <div
        className={`h-full rounded-full bg-sky-500 transition-[width] duration-500 ${value === null ? "w-1/3 animate-pulse" : ""}`}
        style={value === null ? undefined : { width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}
