"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { adminFetch } from "@/lib/admin-client";
import { ApiError } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";

/**
 * Enrolling and managing a TOTP authenticator.
 *
 * Every call here goes to Supabase, not to our API. Supabase generates the
 * secret, renders the QR code and checks the six digits; this app never handles
 * any of it, which is why admin 2FA needed no cryptography of our own.
 *
 * Our API is consulted for one thing only: whether an admin request would now be
 * allowed. That verdict has to come from the server, because the server is where
 * the pinned-factor comparison lives — a second opinion computed in the browser
 * would eventually disagree with it, and the kinder answer would win.
 */

type Factor = { id: string; friendlyName?: string; status: string };
type MfaStatus = {
  satisfied: boolean;
  reason: string | null;
  enrolled: boolean;
  stepped_up: boolean;
  verified_factor_count: number;
};

type Enrolling = { factorId: string; qr: string; secret: string };

export function TwoFactorManager({ isAdmin }: { isAdmin: boolean }) {
  const router = useRouter();
  const [factors, setFactors] = useState<Factor[] | null>(null);
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [enrolling, setEnrolling] = useState<Enrolling | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const supabase = createClient();
    const { data, error: listError } = await supabase.auth.mfa.listFactors();
    if (listError) {
      setError("Could not read your security settings. Reload the page.");
      return;
    }
    setFactors((data?.totp ?? []).map((f) => ({ ...f, status: f.status })));

    // Only admins have a server-side verdict to fetch; for a student the list
    // above is the whole story.
    if (!isAdmin) return;
    try {
      setStatus(await adminFetch<MfaStatus>("/api/admin/mfa"));
    } catch (err) {
      // A 403 here means the account is not an admin any more, which the page
      // should not treat as an error worth shouting about.
      if (!(err instanceof ApiError && err.status === 403)) {
        setError("Could not check your admin access. Reload the page.");
      }
    }
  }, [isAdmin]);

  useEffect(() => {
    // Inside an async body rather than a bare call: nothing here sets state
    // during the render pass, and writing it this way says so to the linter as
    // well as to the reader.
    void (async () => {
      await refresh();
    })();
  }, [refresh]);

  async function beginEnrollment() {
    setBusy(true);
    setError(null);
    setNotice(null);

    const supabase = createClient();
    const { data, error: enrollError } = await supabase.auth.mfa.enroll({
      factorType: "totp",
      friendlyName: `Authenticator ${new Date().toISOString().slice(0, 10)}`,
    });

    if (enrollError || !data) {
      console.error(`[mfa:enroll] ${enrollError?.message ?? "no data"}`);
      setError("Could not start setup. If you already have a code, remove it first.");
      setBusy(false);
      return;
    }

    setEnrolling({ factorId: data.id, qr: data.totp.qr_code, secret: data.totp.secret });
    setBusy(false);
  }

  async function confirmEnrollment() {
    if (!enrolling) return;
    setBusy(true);
    setError(null);

    const supabase = createClient();
    const { data: challenge, error: challengeError } =
      await supabase.auth.mfa.challenge({ factorId: enrolling.factorId });
    if (challengeError || !challenge) {
      setError("Could not verify that code. Try again.");
      setBusy(false);
      return;
    }

    const { error: verifyError } = await supabase.auth.mfa.verify({
      factorId: enrolling.factorId,
      challengeId: challenge.id,
      code: code.trim(),
    });

    if (verifyError) {
      // Not the provider's wording: a wrong code and an expired challenge need
      // the same thing from the user, and saying which is which helps nobody.
      console.error(`[mfa:verify] ${verifyError.message}`);
      setError("That code was not accepted. Check the app and try the next one.");
      setBusy(false);
      return;
    }

    setEnrolling(null);
    setCode("");
    setNotice("Two-factor authentication is on.");
    setBusy(false);
    await refresh();
    // The session is aal2 from here, so anything gated on it re-renders.
    router.refresh();
  }

  async function removeFactor(factorId: string) {
    setBusy(true);
    setError(null);
    const supabase = createClient();
    const { error: unenrollError } = await supabase.auth.mfa.unenroll({ factorId });
    if (unenrollError) {
      console.error(`[mfa:unenroll] ${unenrollError.message}`);
      setError("Could not remove that authenticator.");
      setBusy(false);
      return;
    }
    setBusy(false);
    setNotice("Authenticator removed.");
    await refresh();
    router.refresh();
  }

  async function rotate() {
    setBusy(true);
    setError(null);
    try {
      await adminFetch("/api/admin/mfa/rotate", { method: "POST" });
      setNotice(
        "Ready for a new authenticator. Remove the old one, then set up the new " +
          "one — admin access stays closed until you do.",
      );
      await refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not start replacing your authenticator.",
      );
    }
    setBusy(false);
  }

  const verified = (factors ?? []).filter((f) => f.status === "verified");
  const extraFactors = verified.length > 1;

  return (
    <div className="grid gap-5">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      {notice ? <Alert tone="success">{notice}</Alert> : null}

      {isAdmin && status && !status.satisfied ? (
        <Alert tone="warning">{adminBlockedMessage(status)}</Alert>
      ) : null}

      {isAdmin && extraFactors ? (
        <Alert tone="danger">
          This account has {verified.length} authenticators. Admin access stays
          closed until only the expected one remains — if you did not add the
          extra one, remove it and change your password.
        </Alert>
      ) : null}

      <Card>
        <CardBody className="grid gap-4">
          <div>
            <h2 className="text-base font-semibold text-text">Authenticator app</h2>
            <p className="mt-1 text-sm text-muted">
              A six-digit code from an app on your phone, in addition to your
              password.{" "}
              {isAdmin
                ? "Required for admin access."
                : "Optional, and worth having."}
            </p>
          </div>

          {factors === null ? (
            <p className="text-sm text-muted">Loading…</p>
          ) : verified.length === 0 && !enrolling ? (
            <Button onClick={beginEnrollment} loading={busy} className="justify-self-start">
              Set up two-factor authentication
            </Button>
          ) : null}

          {verified.length > 0 ? (
            <ul className="grid gap-2">
              {verified.map((factor) => (
                <li
                  key={factor.id}
                  className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface px-3 py-2"
                >
                  <span className="text-sm font-medium text-text">
                    {factor.friendlyName || "Authenticator"}
                  </span>
                  <span className="text-xs text-muted">Active</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    loading={busy}
                    onClick={() => removeFactor(factor.id)}
                  >
                    Remove
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}

          {enrolling ? (
            <div className="grid gap-4 rounded-md border border-border bg-surface p-4">
              <div>
                <h3 className="text-sm font-semibold text-text">
                  Scan this with your authenticator app
                </h3>
                <p className="mt-1 text-sm text-muted">
                  Then enter the code it shows. The code changes every 30 seconds.
                </p>
              </div>

              {/* A data: URI from Supabase, rendered by the browser. No request
                  leaves the page, so the secret is not handed to a QR service. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={enrolling.qr}
                alt="Two-factor setup QR code"
                className="size-40 self-start rounded-md bg-white p-2"
              />

              <details className="text-sm text-muted">
                <summary className="cursor-pointer font-medium text-text">
                  Cannot scan it?
                </summary>
                <p className="mt-2">Enter this key in your app by hand:</p>
                <code className="mt-1 block break-all rounded bg-bg px-2 py-1 font-mono text-xs text-text">
                  {enrolling.secret}
                </code>
              </details>

              <Field
                label="Six-digit code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              />

              <div className="flex flex-wrap gap-2">
                <Button
                  onClick={confirmEnrollment}
                  loading={busy}
                  disabled={code.length !== 6}
                >
                  Turn on
                </Button>
                <Button
                  variant="ghost"
                  onClick={() => {
                    // Leaves an unverified factor behind in Supabase, which
                    // counts for nothing: the gate ignores unverified factors.
                    setEnrolling(null);
                    setCode("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}
        </CardBody>
      </Card>

      {isAdmin && status?.enrolled ? (
        <Card>
          <CardBody className="grid gap-3">
            <div>
              <h2 className="text-base font-semibold text-text">
                Replacing your authenticator
              </h2>
              <p className="mt-1 text-sm text-muted">
                Changing phones? Start here while you still have the old one. Your
                admin access closes until the new authenticator is set up — which
                is deliberate: if losing a phone were enough to trust a new code,
                the second factor would not be protecting much.
              </p>
            </div>
            <Button
              variant="secondary"
              onClick={rotate}
              loading={busy}
              className="justify-self-start"
            >
              Start replacing it
            </Button>
            <p className="text-xs text-muted">
              Already lost it? An authenticator cannot be replaced from here
              without the current one — someone with database access has to run{" "}
              <code className="font-mono">scripts/reset_admin_mfa.py</code>.
            </p>
          </CardBody>
        </Card>
      ) : null}

      {isAdmin && status?.satisfied ? (
        <p className="text-sm text-muted">
          <Link href="/admin" className="font-medium text-accent hover:underline">
            Back to the admin area
          </Link>
        </p>
      ) : null}
    </div>
  );
}

/** Fixed copy per server-side reason code, so the page never invents a verdict. */
function adminBlockedMessage(status: MfaStatus): string {
  switch (status.reason) {
    case "mfa_enrollment_required":
      return "Admin access needs two-factor authentication. Set it up below to continue.";
    case "mfa_required":
      return "Set up below is done — now sign in again to enter a code, and admin access returns.";
    case "mfa_factor_mismatch":
      return "The authenticator on this account is not the one it was set up with. Admin access is closed until that is sorted out.";
    default:
      return "Admin access is currently closed on this account.";
  }
}
