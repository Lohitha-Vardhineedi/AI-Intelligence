"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";

import { UploadVideoDialog } from "./UploadVideoDialog";

export function AddVideoButton({ label = "Add new video" }: { label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <span aria-hidden="true" className="text-lg leading-none">
          +
        </span>
        {label}
      </Button>
      {open && <UploadVideoDialog onClose={() => setOpen(false)} />}
    </>
  );
}
