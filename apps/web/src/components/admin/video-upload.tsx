"use client";

import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { adminFetch, type AdminLesson } from "@/lib/admin-client";

type Ticket = {
  video_id: string;
  upload_url: string;
  upload_fields: Record<string, string>;
};

type Phase = "idle" | "uploading" | "processing" | "ready" | "failed";

const STATUS_TONE = {
  absent: "neutral",
  uploading: "warning",
  processing: "warning",
  ready: "success",
  failed: "danger",
} as const;

/**
 * Upload straight to the video provider, then poll until it has encoded.
 *
 * The file never touches our backend — it goes to whatever URL the ticket
 * names. That path is identical for the mock provider and for VdoCipher, which
 * is the point: the code exercised now is the code that will run in production.
 */
export function VideoUpload({
  lesson,
  onChanged,
}: {
  lesson: AdminLesson;
  onChanged: () => void;
}) {
  const [phase, setPhase] = useState<Phase>(
    lesson.video_status === "absent" ? "idle" : (lesson.video_status as Phase),
  );
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Encoding finishes on the provider's schedule, so the only way to know is to
  // ask. Cleared on unmount so navigating away does not leave a timer running.
  useEffect(() => {
    if (phase !== "processing") return;
    pollRef.current = setInterval(async () => {
      try {
        const result = await adminFetch<{ video_status: Phase }>(
          `/api/admin/lessons/${lesson.id}/video/status`,
        );
        if (result.video_status === "ready" || result.video_status === "failed") {
          setPhase(result.video_status);
          onChanged();
        }
      } catch {
        // A failed poll is not a failed upload; the next tick tries again.
      }
    }, 3000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [phase, lesson.id, onChanged]);

  async function upload(file: File) {
    setError(null);
    setPhase("uploading");
    setProgress(0);

    try {
      const ticket = await adminFetch<Ticket>(
        `/api/admin/lessons/${lesson.id}/video/upload`,
        { method: "POST" },
      );

      const form = new FormData();
      for (const [key, value] of Object.entries(ticket.upload_fields)) {
        form.append(key, value);
      }
      form.append("file", file);

      // XHR rather than fetch: fetch still cannot report upload progress, and
      // a 300 MB lecture uploading with no feedback looks like a hang.
      await new Promise<void>((resolve, reject) => {
        const request = new XMLHttpRequest();
        request.open("POST", ticket.upload_url);
        request.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            setProgress(Math.round((event.loaded / event.total) * 100));
          }
        };
        request.onload = () =>
          request.status >= 200 && request.status < 300
            ? resolve()
            : reject(new Error(`upload failed (${request.status})`));
        request.onerror = () => reject(new Error("upload failed"));
        request.send(form);
      });

      setPhase("processing");
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed.");
      setPhase("failed");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge tone={STATUS_TONE[lesson.video_status] ?? "neutral"}>
        {phase === "uploading" ? `uploading ${progress}%` : lesson.video_status}
      </Badge>

      {phase === "processing" ? (
        <span className="text-xs text-subtle">encoding…</span>
      ) : null}

      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void upload(file);
          event.target.value = "";
        }}
      />
      <Button
        type="button"
        variant="ghost"
        size="sm"
        loading={phase === "uploading"}
        onClick={() => inputRef.current?.click()}
      >
        {lesson.video_id ? "Replace video" : "Upload video"}
      </Button>

      {error ? <span className="text-xs font-medium text-danger">{error}</span> : null}
    </div>
  );
}
