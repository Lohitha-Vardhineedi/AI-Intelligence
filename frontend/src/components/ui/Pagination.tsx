import type { Pagination as PageInfo } from "@/types/api";

import { Button } from "./Button";

interface PaginationProps {
  pagination: PageInfo;
  onPageChange: (page: number) => void;
  label: string;
}

/** Renders nothing when everything fits on one page. */
export function Pagination({ pagination, onPageChange, label }: PaginationProps) {
  const { page, pages } = pagination;
  if (pages <= 1) return null;
  return (
    <nav aria-label={label} className="flex items-center justify-end gap-3 text-sm">
      <Button variant="secondary" onClick={() => onPageChange(page - 1)} disabled={page <= 1}>
        Previous
      </Button>
      <span className="text-slate-400">
        Page {page} of {pages}
      </span>
      <Button variant="secondary" onClick={() => onPageChange(page + 1)} disabled={page >= pages}>
        Next
      </Button>
    </nav>
  );
}
