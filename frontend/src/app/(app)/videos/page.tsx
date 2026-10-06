import type { Metadata } from "next";

import { AddVideoButton } from "@/components/videos/AddVideoButton";
import { VideoList } from "@/components/videos/VideoList";

export const metadata: Metadata = { title: "Videos" };

export default function VideosPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Videos</h1>
          <p className="mt-1 text-sm text-slate-400">
            Upload recordings to detect, track and count people and objects.
          </p>
        </div>
        <AddVideoButton />
      </div>
      <VideoList />
    </div>
  );
}
