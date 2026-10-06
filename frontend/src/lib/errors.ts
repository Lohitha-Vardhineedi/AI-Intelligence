import type { ApiErrorBody } from "@/types/api";

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ApiErrorBody).error?.message === "string"
  );
}

/** A readable message from an RTK Query error, an API error body or a thrown Error. */
export function errorMessage(error: unknown): string {
  if (isApiErrorBody(error)) return error.error.message;
  if (typeof error === "object" && error !== null) {
    if ("data" in error && isApiErrorBody(error.data)) return error.data.error.message;
    if ("status" in error && error.status === "FETCH_ERROR") {
      return "Can't reach the server. Is the backend running?";
    }
    if ("message" in error && typeof error.message === "string") return error.message;
  }
  return "Something went wrong";
}
