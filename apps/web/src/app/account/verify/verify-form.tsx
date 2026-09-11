"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { safeNextPath } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase/client";

/**
 * The step-up challenge: a session that has a password but not yet a code.
 *
 * Supabase raises the session's assurance level to aal2 when the code checks
 * out; nothing here decides anything. Our API then sees `aal2` in the token and
 * lets admin requests through — which is why this page needs no cooperation from
 * the backend at all.
 */
export function VerifyForm({ next }: { next: string }) {
  const router = useRouter();
  const [factorId, setFactorId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const target = safeNextPath(next, "/admin");

  useEffect(() => {
    void (async () => {
      const supabase = createClient();
      const { data } = await supabase.auth.mfa.listFactors();
      const verified = (data?.totp ?? []).filter((f) => f.status === "verified");
      // No verified factor means there is nothing to challenge. Sending them to
      // setup is the only useful thing this page can do.
      if (verified.length === 0) {
        router.replace("/account/security");
        return;
      }
      setFactorId(verified[0]!.id);
      setReady(true);
    })();
  }, [router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!factorId) return;
    setBusy(true);
    setError(null);

    const supabase = createClient();
    const { data: challenge, error: challengeError } =
      await supabase.auth.mfa.challenge({ factorId });
    if (challengeError || !challenge) {
      console.error(`[mfa:challenge] ${challengeError?.message ?? "no data"}`);
      setError("Could not check that code. Try again in a moment.");
      setBusy(false);
      return;
    }

    const { error: verifyError } = await supabase.auth.mfa.verify({
      factorId,
      challengeId: challenge.id,
      code: code.trim(),
    });

    if (verifyError) {
      // One message for a wrong code, a reused code and an expired challenge.
      // Supabase already rate-limits the attempts; telling the guesser which of
      // the three happened is the only thing that would help them.
      console.error(`[mfa:verify] ${verifyError.message}`);
      setError("That code was not accepted. Wait for the next one and try again.");
      setCode("");
      setBusy(false);
      return;
    }

    router.replace(target);
    router.refresh();
  }

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md items-center px-4 py-12">
      <div className="w-full">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          Enter your code
        </h1>
        <p className="mt-1.5 text-sm text-muted">
          Admin access needs the six-digit code from your authenticator app.
        </p>

        <Card className="mt-6">
          <CardBody>
            <form onSubmit={onSubmit} className="grid gap-4" noValidate>
              {error ? <Alert tone="danger">{error}</Alert> : null}
              <Field
                label="Six-digit code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                autoFocus
                required
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                hint="It changes every 30 seconds."
              />
              <Button
                type="submit"
                loading={busy}
                disabled={!ready || code.length !== 6}
                className="mt-1 w-full"
              >
                Continue
              </Button>
            </form>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
