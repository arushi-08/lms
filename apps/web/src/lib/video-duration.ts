/**
 * Reading a video's length in the browser.
 *
 * Duration decides when a lesson counts as watched, so it is read on the
 * *authoring* side — from the file an admin uploads, or from an admin's own
 * playback of it — and never from a student's player. A student able to report
 * it would report one second and finish the lesson instantly.
 *
 * Both paths are best effort: a container the browser cannot parse yields null,
 * and the lesson falls back to manual completion rather than being stranded.
 */

const TIMEOUT_MS = 20_000;

function readDuration(src: string, revoke: boolean): Promise<number | null> {
  return new Promise((resolve) => {
    const element = document.createElement("video");
    let settled = false;

    const finish = (value: number | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (revoke) URL.revokeObjectURL(src);
      element.src = "";
      resolve(value);
    };

    // A stalled network request would otherwise leave the caller waiting
    // forever with a spinner and no way out.
    const timer = setTimeout(() => finish(null), TIMEOUT_MS);

    element.preload = "metadata";
    element.crossOrigin = "anonymous";
    element.onloadedmetadata = () =>
      finish(
        Number.isFinite(element.duration) && element.duration > 0
          ? Math.round(element.duration)
          : null,
      );
    element.onerror = () => finish(null);
    element.src = src;
  });
}

/** Length of a file the admin is about to upload. */
export function readDurationFromFile(file: File): Promise<number | null> {
  return readDuration(URL.createObjectURL(file), true);
}

/** Length of a video already uploaded, via a playback URL. */
export function readDurationFromUrl(url: string): Promise<number | null> {
  return readDuration(url, false);
}
