"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * A YouTube lesson, played inside the course.
 *
 * The point of embedding rather than linking out is that the student stays
 * here and their progress is tracked. That second half is why this uses the
 * IFrame Player API rather than a plain `<iframe>`: a bare embed plays fine and
 * tells us nothing, so the progress bar would never move and the lesson could
 * never complete.
 *
 * The player reports position; this component turns that into the same
 * forward-only accumulation the uploaded-video player does, and hands it to the
 * same heartbeat. The server clamps it either way, so a YouTube lesson is no
 * more trustworthy and no less than any other.
 *
 * What it does not do is pretend the video is protected. It is public on
 * YouTube, the branding stays, and the "Watch on YouTube" affordance is part of
 * the player we are required to show unmodified.
 */

const API_SRC = "https://www.youtube.com/iframe_api";

/** How often to sample position. The API has no timeupdate event. */
const POLL_MS = 1000;

type Player = {
  getCurrentTime: () => number;
  getDuration: () => number;
  destroy: () => void;
};

type YT = {
  Player: new (el: HTMLElement, options: Record<string, unknown>) => Player;
  PlayerState: { PLAYING: number; PAUSED: number; ENDED: number };
};

declare global {
  interface Window {
    YT?: YT;
    onYouTubeIframeAPIReady?: () => void;
  }
}

/**
 * Load the IFrame API once per page, no matter how many players mount.
 *
 * The API calls a single global callback when it is ready, so two components
 * each installing their own would leave one of them waiting forever.
 */
let apiReady: Promise<YT> | null = null;

function loadApi(): Promise<YT> {
  if (apiReady) return apiReady;

  apiReady = new Promise<YT>((resolve, reject) => {
    if (window.YT?.Player) {
      resolve(window.YT);
      return;
    }

    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      previous?.();
      if (window.YT?.Player) resolve(window.YT);
      else reject(new Error("the YouTube player loaded without its API"));
    };

    const existing = document.querySelector(`script[src="${API_SRC}"]`);
    if (existing) return;

    const script = document.createElement("script");
    script.src = API_SRC;
    // Reject rather than hang: a blocked script -- an extension, a CSP
    // mistake, a corporate proxy -- otherwise leaves a permanent spinner with
    // nothing in any log to explain it.
    script.onerror = () =>
      reject(new Error("the YouTube player could not be loaded"));
    document.head.appendChild(script);
  });

  return apiReady;
}

export function YouTubePlayer({
  videoId,
  startSeconds,
  onTick,
  onEnded,
  onError,
}: {
  videoId: string;
  startSeconds: number;
  /** Called about once a second with the player's current position. */
  onTick: (currentTime: number) => void;
  onEnded: (currentTime: number) => void;
  onError: (message: string) => void;
}) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  // Held in refs so that a parent re-render with new callbacks never tears
  // down and rebuilds the player mid-lesson, which would restart the video.
  // Written in an effect rather than during render: a ref write during render
  // is not guaranteed to have happened by the time anything reads it.
  const onTickRef = useRef(onTick);
  const onEndedRef = useRef(onEnded);
  const onErrorRef = useRef(onError);
  const startRef = useRef(startSeconds);

  useEffect(() => {
    onTickRef.current = onTick;
    onEndedRef.current = onEnded;
    onErrorRef.current = onError;
  }, [onTick, onEnded, onError]);

  const mount = useCallback(async () => {
    const host = mountRef.current;
    if (!host) return () => {};

    let player: Player | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    let cancelled = false;

    try {
      const YT = await loadApi();
      if (cancelled || !mountRef.current) return () => {};

      player = new YT.Player(host, {
        videoId,
        host: "https://www.youtube-nocookie.com",
        playerVars: {
          // Resume where they left off.
          start: Math.max(0, Math.floor(startRef.current)),
          // Required for the API to accept commands and emit events from a
          // page that is not youtube.com.
          origin: window.location.origin,
          playsinline: 1,
          rel: 0,
        },
        events: {
          onReady: () => {
            timer = setInterval(() => {
              if (!player) return;
              onTickRef.current(player.getCurrentTime());
            }, POLL_MS);
          },
          onStateChange: (event: { data: number }) => {
            if (!player) return;
            if (event.data === YT.PlayerState.ENDED) {
              onEndedRef.current(player.getCurrentTime());
            }
          },
          onError: () => {
            // The usual causes are a video that has been deleted, made
            // private, or marked not-embeddable by its owner -- all of which
            // are fixed in YouTube, not here, so say so.
            onErrorRef.current(
              "This video is unavailable. It may have been removed, made " +
                "private, or set to block embedding.",
            );
          },
        },
      });
    } catch (cause) {
      if (!cancelled) {
        onErrorRef.current(
          cause instanceof Error ? cause.message : "The video player failed to load.",
        );
      }
    }

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      // Without this the iframe and its polling survive a lesson change and
      // two lessons report progress at once.
      try {
        player?.destroy();
      } catch {
        // Already gone with the unmounted node; nothing to clean up.
      }
    };
  }, [videoId]);

  useEffect(() => {
    let dispose: (() => void) | undefined;
    let disposed = false;

    void mount().then((cleanup) => {
      if (disposed) cleanup();
      else dispose = cleanup;
    });

    return () => {
      disposed = true;
      dispose?.();
    };
  }, [mount]);

  return (
    <div className="aspect-video w-full overflow-hidden rounded-lg bg-black">
      {/* Replaced by the player's iframe once the API is ready. */}
      <div ref={mountRef} className="size-full" />
    </div>
  );
}
