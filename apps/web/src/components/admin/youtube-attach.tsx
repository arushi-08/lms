"use client";

import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { adminFetch, type AdminLesson } from "@/lib/admin-client";
import { ApiError } from "@/lib/api";

/**
 * Point a lesson at a video that already lives on YouTube.
 *
 * The alternative to this is uploading the clip here, which protects it. These
 * two are not interchangeable and the UI says so rather than presenting them
 * as a toggle between equivalent options: a YouTube video stays public
 * wherever it is embedded, and no setting on this page changes that.
 *
 * Parsing happens on the server (app/domain/youtube.py) and the message it
 * returns is shown verbatim, because it is about what the admin just pasted
 * and is the fastest way for them to see what was wrong with it.
 */
export function YouTubeAttach({
  lesson,
  onChanged,
}: {
  lesson: AdminLesson;
  onChanged: () => void;
}) {
  const attached = lesson.video_source === "youtube";
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function attach(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adminFetch(`/api/admin/lessons/${lesson.id}/youtube`, {
        method: "PUT",
        body: { url },
      });
      setUrl("");
      onChanged();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Could not attach that video.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function detach() {
    setBusy(true);
    setError(null);
    try {
      await adminFetch(`/api/admin/lessons/${lesson.id}/youtube`, {
        method: "DELETE",
      });
      onChanged();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "Could not remove that video.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (attached) {
    return (
      <div className="grid gap-2">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface px-3 py-2">
          <span className="text-sm text-text">On YouTube</span>
          <code className="font-mono text-xs text-muted">{lesson.video_id}</code>
          <a
            href={`https://www.youtube.com/watch?v=${lesson.video_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium text-accent hover:underline"
          >
            Open on YouTube
          </a>
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto"
            loading={busy}
            onClick={detach}
          >
            Remove
          </Button>
        </div>
        <p className="text-xs text-muted">
          Public wherever it is embedded — anyone with the link can watch it
          outside this course. Fine for free material; upload the file instead
          for anything that should stay behind enrollment.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={attach} className="grid gap-2">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <div className="flex flex-wrap items-end gap-2">
        <Field
          label="…or use a YouTube video"
          placeholder="https://www.youtube.com/watch?v=…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="min-w-60 flex-1"
          hint="Watch, youtu.be, Shorts or embed links all work."
        />
        <Button type="submit" variant="secondary" loading={busy} disabled={!url.trim()}>
          Attach
        </Button>
      </div>
    </form>
  );
}
