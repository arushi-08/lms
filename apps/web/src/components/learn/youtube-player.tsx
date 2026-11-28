"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";

/**
 * A YouTube lesson, played inside the course.
 *
 * The point of embedding rather than linking out is that the student stays here
 * and their progress is tracked. That second half is why this uses the IFrame
 * Player API rather than a plain `<iframe>`: a bare embed plays fine and tells
 * us nothing, so the progress bar would never move and the lesson could never
 * complete.
 *
 * Two things in here are the result of this failing in use, and both are worth
 * keeping:
 *
 * **It never shows a silent black box.** Every way this can fail now renders a
 * sentence. The first version handed failures to a parent callback that the
 * parent, in the branch that renders this component, never displayed — so a
 * blocked script, an unembeddable video and a typo'd id all looked identical:
 * a black rectangle and nothing else, anywhere.
 *
 * **It mounts into a throwaway child, not the node React owns.** `YT.Player`
 * *replaces* the element it is given with an iframe. Handing it a ref'd node
 * means React is holding a pointer to something that no longer exists, and with
 * `reactStrictMode` on, effects run twice in development — the first player is
 * built after the first cleanup has already run, and the second builds against
 * a node the first one removed. A black box, intermittently, in dev only, which
 * is the worst possible shape for a bug.
 */

const API_SRC = "https://www.youtube.com/iframe_api";

/** How often to sample position. The API has no timeupdate event. */
const POLL_MS = 1000;

/**
 * How long to wait for the player to say it is ready before giving up.
 *
 * Generous: a cold CDN fetch on a slow connection is legitimately a few
 * seconds. What this catches is the case where nothing is coming at all --
 * an extension blocking YouTube, a network that cannot reach it, a CSP that
 * refuses the frame -- none of which produce an error event.
 */
const READY_TIMEOUT_MS = 15_000;

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
 * What YouTube's error codes mean, as far as we can act on them.
 *
 * Each maps to something the person reading it could do. "An error occurred"
 * sends an admin to the wrong place; "the owner has disabled embedding" sends
 * them to YouTube Studio, which is where the fix is.
 */
function describeError(code: number): string {
  switch (code) {
    case 2:
      return "That video id is not valid. Re-paste the link in the admin panel.";
    case 5:
      return "The video player could not play this video in this browser.";
    case 100:
      return "That video does not exist on YouTube any more, or has been made private.";
    case 101:
    case 150:
      return (
        "The owner of this video has disabled playing it on other sites. " +
        "In YouTube Studio, set it to allow embedding."
      );
    default:
      return `YouTube refused to play this video (error ${code}).`;
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
    script.onerror = () => {
      // A failed load must not be cached as the answer: the next lesson should
      // get a fresh attempt rather than inheriting this rejection forever.
      apiReady = null;
      reject(
        new Error(
          "Could not load the YouTube player. It may be blocked by a browser " +
            "extension, an ad blocker, or this network.",
        ),
      );
    };
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
  /** For the caller's own logging. The message is rendered here regardless. */
  onError?: (message: string) => void;
}) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

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

  const fail = useCallback((message: string) => {
    setProblem(message);
    onErrorRef.current?.(message);
  }, []);

  const mount = useCallback(async () => {
    const container = mountRef.current;
    if (!container) return () => {};

    let player: Player | null = null;
    let timer: ReturnType<typeof setInterval> | null = null;
    let readyTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    // A child of our own making. YT.Player replaces whatever element it is
    // given, so it must never be the node React is holding a ref to.
    container.replaceChildren();
    const target = document.createElement("div");
    container.appendChild(target);

    const cleanup = () => {
      cancelled = true;
      if (timer) clearInterval(timer);
      if (readyTimer) clearTimeout(readyTimer);
      try {
        player?.destroy();
      } catch {
        // Already gone with the unmounted node; nothing to clean up.
      }
      // Whatever YouTube left behind goes with it, so a remount starts clean
      // rather than stacking a second iframe on the first.
      container.replaceChildren();
    };

    try {
      const YT = await loadApi();
      if (cancelled || !mountRef.current) return cleanup;

      // Cleared by onReady. If it fires, the player never started -- which is
      // the whole point, so there is no "but the player object exists" case to
      // exempt here: a constructed player that never signals ready is exactly
      // the black box this is for.
      readyTimer = setTimeout(() => {
        if (cancelled) return;
        fail(
          "The video player did not start. It may be blocked by a browser " +
            "extension, an ad blocker, or this network.",
        );
      }, READY_TIMEOUT_MS);

      player = new YT.Player(target, {
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
            if (cancelled) return;
            if (readyTimer) clearTimeout(readyTimer);
            setReady(true);
            timer = setInterval(() => {
              if (!player) return;
              onTickRef.current(player.getCurrentTime());
            }, POLL_MS);
          },
          onStateChange: (event: { data: number }) => {
            if (!player || cancelled) return;
            if (event.data === YT.PlayerState.ENDED) {
              onEndedRef.current(player.getCurrentTime());
            }
          },
          onError: (event: { data: number }) => {
            if (cancelled) return;
            if (readyTimer) clearTimeout(readyTimer);
            fail(describeError(event.data));
          },
        },
      });
    } catch (cause) {
      if (!cancelled) {
        fail(
          cause instanceof Error ? cause.message : "The video player failed to load.",
        );
      }
    }

    return cleanup;
  }, [videoId, fail]);

  useEffect(() => {
    // No state reset here: the caller keys this component by video id, so a
    // different video remounts it with fresh state rather than reusing an
    // instance that is still holding the previous one's error.
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

  if (problem) {
    return (
      <div className="grid gap-2">
        <Alert tone="danger">{problem}</Alert>
        <p className="text-xs text-muted">
          You can still watch it on{" "}
          <a
            href={`https://www.youtube.com/watch?v=${videoId}`}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-accent hover:underline"
          >
            YouTube
          </a>
          , though your progress will not be recorded there.
        </p>
      </div>
    );
  }

  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-lg bg-black">
      {!ready ? (
        <p className="absolute inset-0 grid place-items-center text-sm text-white/70">
          Loading the video…
        </p>
      ) : null}
      {/* Our own child goes in here and is what YouTube replaces. */}
      <div ref={mountRef} className="relative size-full" />
    </div>
  );
}
