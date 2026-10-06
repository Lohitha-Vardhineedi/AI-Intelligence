"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, type DragEvent } from "react";

import { ErrorMessage } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { ACCEPTED_VIDEO_EXTENSIONS, MAX_UPLOAD_MB } from "@/lib/config";
import { formatBytes } from "@/lib/format";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { resetUpload, uploadVideo } from "@/store/slices/videoSlice";

function validate(file: File): string | null {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ACCEPTED_VIDEO_EXTENSIONS.includes(extension)) {
    return "Choose an MP4, AVI, MOV or MKV video.";
  }
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) {
    return `The video is larger than ${MAX_UPLOAD_MB} MB.`;
  }
  return null;
}

export function UploadVideoDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const uploadRef = useRef<{ abort: () => void } | null>(null);
  const inputId = useId();
  const router = useRouter();
  const dispatch = useAppDispatch();
  const upload = useAppSelector((state) => state.video.upload);
  const [file, setFile] = useState<File | null>(null);
  const [invalid, setInvalid] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const busy = upload.status === "uploading" || upload.status === "starting";

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  const close = () => {
    if (busy) return;
    dispatch(resetUpload());
    onClose();
  };

  const choose = (selected: File | undefined) => {
    if (!selected) return;
    setFile(selected);
    setInvalid(validate(selected));
    dispatch(resetUpload());
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (!busy) choose(event.dataTransfer.files[0]);
  };

  const submit = async () => {
    if (!file || invalid) return;
    const pending = dispatch(uploadVideo(file));
    uploadRef.current = pending;
    const result = await pending;
    uploadRef.current = null;
    if (uploadVideo.fulfilled.match(result)) {
      onClose();
      router.push(`/videos/${result.payload.id}`);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={`${inputId}-title`}
      onCancel={(event) => {
        event.preventDefault(); // Escape: close only when nothing is uploading
        close();
      }}
      className="m-auto w-full max-w-lg rounded-lg border border-slate-700 bg-slate-900 p-0 text-slate-100 backdrop:bg-black/70"
    >
      <div className="space-y-5 p-6">
        <div>
          <h2 id={`${inputId}-title`} className="text-lg font-semibold">
            Add new video
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            It is analysed as soon as the upload finishes: people and objects are detected,
            tracked and counted, and zone and line events are raised.
          </p>
        </div>

        <label
          htmlFor={inputId}
          onDragOver={(event) => {
            event.preventDefault();
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-sky-400 ${
            dragging ? "border-sky-400 bg-sky-500/10" : "border-slate-700 hover:border-slate-500"
          } ${busy ? "pointer-events-none opacity-60" : ""}`}
        >
          <input
            id={inputId}
            type="file"
            accept={[...ACCEPTED_VIDEO_EXTENSIONS, "video/*"].join(",")}
            className="sr-only"
            disabled={busy}
            onChange={(event) => choose(event.target.files?.[0])}
          />
          <span className="text-sm text-slate-200">
            Drag a video here, or <span className="text-sky-400 underline">browse</span>
          </span>
          <span className="text-xs text-slate-400">
            MP4, AVI, MOV or MKV, up to {MAX_UPLOAD_MB / 1024} GB
          </span>
        </label>

        {file && (
          <div className="flex items-center justify-between gap-4 rounded-md bg-slate-800/70 px-4 py-3 text-sm">
            <span className="truncate font-medium" title={file.name}>
              {file.name}
            </span>
            <span className="shrink-0 text-slate-400">{formatBytes(file.size)}</span>
          </div>
        )}

        {busy && (
          <div className="space-y-2">
            <ProgressBar value={upload.progress} label="Upload progress" />
            <p className="text-xs text-slate-400" aria-live="polite">
              {upload.status === "uploading"
                ? `Uploading… ${upload.progress}%`
                : "Upload complete. Starting analysis…"}
            </p>
          </div>
        )}

        {(invalid || upload.error) && <ErrorMessage>{invalid ?? upload.error}</ErrorMessage>}

        <p className="text-xs text-slate-500">
          Footage from a fixed camera works best. Zones and lines come from the scene
          configuration (backend/config/scene.yaml).
        </p>

        <div className="flex justify-end gap-3">
          {busy ? (
            <Button
              variant="secondary"
              onClick={() => uploadRef.current?.abort()}
              disabled={upload.status !== "uploading"}
            >
              Cancel upload
            </Button>
          ) : (
            <Button variant="secondary" onClick={close}>
              Close
            </Button>
          )}
          <Button onClick={submit} disabled={!file || Boolean(invalid) || busy}>
            Upload and analyse
          </Button>
        </div>
      </div>
    </dialog>
  );
}
