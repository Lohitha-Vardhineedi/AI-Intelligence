import type { ApiErrorBody, ApiResponse } from "@/types/api";

/**
 * Uploads a file as multipart form data and reports progress (0-100).
 * fetch() can't report upload progress, so this uses XMLHttpRequest.
 */
export function uploadFile<T>(
  url: string,
  file: File,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.responseType = "json";

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      const body = xhr.response as ApiResponse<T> | ApiErrorBody | null;
      if (xhr.status >= 200 && xhr.status < 300 && body?.success) {
        resolve(body.data);
      } else {
        reject(body ?? new Error(`Upload failed (HTTP ${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error("Can't reach the server. Is the backend running?"));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
