"use client";

import { useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { adminFetch } from "@/lib/admin-client";
import type { PlaybackGrant } from "@/lib/api";

const HEARTBEAT_SECONDS = 20;

/**
 * Plays one lesson, and reports progress while it does.
 *
 * The grant is minted when the viewer presses play, not when the page loads.
 * Two reasons: a playback grant is short lived and consumes one of the
 * viewer's concurrent-session slots, so issuing one just because a page was
 * opened would let ordinary browsing lock someone out of their own account;
 * and it means no OTP is created for a lesson nobody watches.
 *
 * With VdoCipher the grant is an OTP handed to their iframe and no stream URL
 * exists on our side at all. With the mock it is a direct URL to the uploaded
 * file. The entitlement check that produces either is the same code.
 */
export function VideoPlayer({
  lessonId,
  onProgress,
}: {
  lessonId: string;
  onProgress?: (percent: number, completed: boolean) => void;
}) {
  const [grant, setGrant] = useState<PlaybackGrant | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const lastSent = useRef(0);

  async function start() {
    setLoading(true);
    setError(null);
    try {
      setGrant(
        await adminFetch<PlaybackGrant>(`/api/lessons/${lessonId}/playback`, {
          method: "POST",
        }),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start playback.");
    } finally {
      setLoading(false);
    }
  }

  // Throttled here and clamped on the server. The client side saves needless
  // requests; the server side is what makes the number trustworthy.
  async function beat(watched: number, position: number) {
    if (watched - lastSent.current < HEARTBEAT_SECONDS) return;
    lastSent.current = watched;
    try {
      const result = await adminFetch<{
        course_progress_percent: number;
        completed: boolean;
      }>(`/api/lessons/${lessonId}/progress`, {
        method: "POST",
        body: {
          watched_seconds: Math.floor(watched),
          position_seconds: Math.floor(position),
        },
      });
      onProgress?.(result.course_progress_percent, result.completed);
    } catch {
      // A dropped heartbeat is not worth interrupting playback for; the next
      // one carries the cumulative total anyway.
    }
  }

  if (!grant) {
    return (
      <div className="grid gap-3">
        <div className="grid aspect-video w-full place-items-center rounded-lg border border-border bg-surface-sunken">
          {error ? (
            <div className="max-w-sm px-6 text-center">
              <Alert tone="danger">{error}</Alert>
              <Button
                variant="secondary"
                size="sm"
                className="mt-3"
                onClick={() => void start()}
              >
                Try again
              </Button>
            </div>
          ) : (
            <Button size="lg" loading={loading} onClick={() => void start()}>
              <svg viewBox="0 0 24 24" className="size-4" fill="currentColor" aria-hidden>
                <path d="M8 5v14l11-7z" />
              </svg>
              Play lesson
            </Button>
          )}
        </div>
      </div>
    );
  }

  if (!grant.direct_url) {
    return (
      <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
        <iframe
          title="Lesson video"
          src={`https://player.vdocipher.com/v2/?otp=${encodeURIComponent(
            grant.otp,
          )}&playbackInfo=${encodeURIComponent(grant.playback_info)}`}
          allow="encrypted-media"
          allowFullScreen
          className="size-full border-0"
        />
      </div>
    );
  }

  return (
    <video
      src={grant.direct_url}
      controls
      autoPlay
      controlsList="nodownload"
      onContextMenu={(event) => event.preventDefault()}
      className="aspect-video w-full rounded-lg bg-black"
      onTimeUpdate={(event) => {
        const el = event.currentTarget;
        void beat(el.currentTime, el.currentTime);
      }}
      onEnded={(event) => {
        const el = event.currentTarget;
        lastSent.current = 0;
        void beat(el.duration || el.currentTime, el.currentTime);
      }}
    />
  );
}
