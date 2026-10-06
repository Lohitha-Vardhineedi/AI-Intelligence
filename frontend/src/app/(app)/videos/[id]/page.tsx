import type { Metadata } from "next";

import { VideoDetail } from "@/components/videos/VideoDetail";

export const metadata: Metadata = { title: "Video analysis" };

export default async function VideoPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <VideoDetail id={id} />;
}
