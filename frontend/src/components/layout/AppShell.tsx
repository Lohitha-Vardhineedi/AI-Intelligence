import Link from "next/link";
import type { ReactNode } from "react";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-800 bg-slate-950/80">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-8 px-4 sm:px-6">
          <Link href="/videos" className="font-semibold tracking-tight text-slate-50">
            AI Video Intelligence
          </Link>
          <nav aria-label="Main">
            <Link href="/videos" className="text-sm text-slate-300 hover:text-slate-50">
              Videos
            </Link>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">{children}</main>
    </div>
  );
}
