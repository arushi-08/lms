/**
 * Content Security Policy, in a module both next.config.ts and a test can read.
 *
 * Extracted so the policy is checkable without booting a server. The last bug
 * here cost an evening: connect-src omitted the API origin, so the browser
 * refused every direct call to the backend *before sending it*. Nothing reached
 * the API log, and fetch reported only "Failed to fetch". A test that never
 * loads a page carrying this header cannot catch that — which is exactly what
 * happened.
 */

export const DEFAULT_API_URL = "http://localhost:8000";

export function apiOriginFrom(raw) {
  try {
    return new URL(raw || DEFAULT_API_URL).origin;
  } catch {
    // A malformed value should not take the config down; the app's own env
    // check reports it far more clearly.
    return DEFAULT_API_URL;
  }
}

export function buildCsp(apiUrl) {
  const api = apiOriginFrom(apiUrl);
  return [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://js.stripe.com",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "media-src 'self' blob: https:",
    "font-src 'self' data:",
    // The browser talks to the API directly for playback grants, progress,
    // quiz submission and every admin mutation.
    `connect-src 'self' ${api} https://*.supabase.co wss://*.supabase.co https://api.stripe.com`,
    "frame-src https://player.vdocipher.com https://js.stripe.com https://hooks.stripe.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}
