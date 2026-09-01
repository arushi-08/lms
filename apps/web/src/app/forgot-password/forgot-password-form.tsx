"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { reportAuthError } from "@/lib/auth-errors";
import { createClient } from "@/lib/supabase/client";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);

    const supabase = createClient();
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      // Land on the callback so the recovery code becomes a session, then hand
      // off to the form that actually sets the new password.
      redirectTo: `${window.location.origin}/auth/callback?next=/reset-password`,
    });

    if (error) reportAuthError("resetPasswordForEmail", error);

    // Same screen either way. Confirming whether an address is registered here
    // would make this form an account checker.
    setSent(true);
    setLoading(false);
  }

  if (sent) {
    return (
      <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md items-center px-4 py-12">
        <Card className="w-full">
          <CardBody className="text-center">
            <h1 className="text-lg font-semibold text-text">Check your email</h1>
            <p className="mt-1.5 text-sm text-muted">
              If <span className="font-medium text-text">{email}</span> has an
              account, a reset link is on its way. It expires in an hour.
            </p>
            <Link href="/login" className="mt-5 inline-block">
              <Button variant="secondary" size="sm">
                Back to sign in
              </Button>
            </Link>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md items-center px-4 py-12">
      <div className="w-full">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          Reset your password
        </h1>
        <p className="mt-1.5 text-sm text-muted">
          We will email you a link to set a new one.
        </p>

        <Card className="mt-6">
          <CardBody>
            <form onSubmit={onSubmit} className="grid gap-4" noValidate>
              <Field
                label="Email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <Button type="submit" loading={loading} className="mt-1 w-full">
                Send reset link
              </Button>
            </form>
          </CardBody>
        </Card>

        <p className="mt-5 text-center text-sm text-muted">
          Remembered it?{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
