export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Absolute URL of a backend path, e.g. apiUrl("/videos/1/annotated"). */
export const apiUrl = (path: string): string => `${API_URL}/api/v1${path}`;

export const ACCEPTED_VIDEO_EXTENSIONS = [".mp4", ".avi", ".mov", ".mkv"];
export const MAX_UPLOAD_MB = 1024;
