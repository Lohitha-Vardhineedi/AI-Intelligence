/** Response envelopes used by every backend endpoint. */

export interface ApiResponse<T> {
  success: true;
  data: T;
}

export interface Pagination {
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface PagedResponse<T> {
  success: true;
  data: T[];
  pagination: Pagination;
}

export interface Page<T> {
  items: T[];
  pagination: Pagination;
}

export interface ApiErrorBody {
  success: false;
  error: { code: string; message: string };
}
