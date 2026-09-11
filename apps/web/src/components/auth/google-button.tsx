"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { safeNextPath } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase/client";

/**
 * "Continue with Google" — one button for both signing in and signing up.
 *
 * There is no separate registration path: Google either hands back an identity
 * we already know or one we do not, and Supabase creates the account in the
 * second case. Offering two buttons would imply a choice the user does not have
 * to make, and a "sign up" button that fails because the account exists is a
 * worse experience than one that just works.
 *
 * The account it creates is a student. The role lives in a column with a
 * `student` default and is never read from provider metadata — see migration
 * 0013 — so this cannot be a route to an admin account.
 */
export function GoogleButton({ next, label }: { next?: string; label?: string }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn() {
    setLoading(true);
    setError(null);

    // Validate before it leaves, not only on the way back. Supabase echoes
    // redirectTo into the provider round trip, and a value that is checked in
    // only one of the two places is a value that is effectively unchecked.
    const target = safeNextPath(next);
    const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(target)}`;

    const supabase = createClient();
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo,
        // Ask for the account picker rather than silently reusing whichever
        // Google account the browser is already signed into. On a shared
        // machine, "continue" landing someone in a stranger's account is both a
        // support ticket and a privacy problem.
        queryParams: { prompt: "select_account" },
      },
    });

    if (oauthError) {
      // A failure here means the redirect never happened, so the page is still
      // ours to render on.
      console.error(`[auth:google] ${oauthError.message}`);
      setError("Google sign-in is unavailable right now. Try email instead.");
      setLoading(false);
    }
    // On success the browser is already navigating away; leaving the button in
    // its loading state is exactly right.
  }

  return (
    <div className="grid gap-2">
      <Button
        type="button"
        variant="secondary"
        className="w-full"
        loading={loading}
        onClick={signIn}
      >
        <span className="flex items-center justify-center gap-2">
          <GoogleMark />
          {label ?? "Continue with Google"}
        </span>
      </Button>
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/** Google's mark, inline so no request leaves the page to render a button. */
function GoogleMark() {
  return (
    <svg viewBox="0 0 18 18" className="size-4 shrink-0" aria-hidden focusable="false">
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.62Z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.34A8.99 8.99 0 0 0 9 18Z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.94H.96a9 9 0 0 0 0 8.12l3.01-2.34Z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59C13.46.89 11.43 0 9 0A8.99 8.99 0 0 0 .96 4.94l3.01 2.34C4.68 5.16 6.66 3.58 9 3.58Z"
      />
    </svg>
  );
}

/** A labelled rule, so the two ways in read as alternatives rather than steps. */
export function AuthDivider() {
  return (
    <div className="flex items-center gap-3" aria-hidden>
      <span className="h-px flex-1 bg-border" />
      <span className="text-xs font-medium text-muted">or</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}
