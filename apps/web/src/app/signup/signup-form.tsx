"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthDivider, GoogleButton } from "@/components/auth/google-button";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { describeSignUpError } from "@/lib/auth-errors";
import { createClient } from "@/lib/supabase/client";

const MIN_PASSWORD = 10;

export function SignupForm() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters.`);
      return;
    }

    setLoading(true);
    setError(null);

    const supabase = createClient();
    const { error: signUpError } = await supabase.auth.signUp({
      email,
      password,
      options: {
        // Read by the handle_new_user trigger to populate profiles.full_name,
        // which is what later gets printed on the certificate.
        data: { full_name: fullName.trim() },
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (signUpError) {
      // Supabase's own wording, straight onto the page, is how "User already
      // registered" turns this form into an account checker.
      const { message, alreadyRegistered } = describeSignUpError(signUpError);
      if (!alreadyRegistered) {
        setError(message);
        setLoading(false);
        return;
      }
      // Fall through to the confirmation screen: the address is taken, Supabase
      // has told its owner, and this page says exactly what it says to everyone.
    }

    // Always the same confirmation screen, whether or not the address was
    // already registered — otherwise this page becomes an account checker.
    setSent(true);
    setLoading(false);
  }

  if (sent) {
    return (
      <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md items-center px-4 py-12">
        <Card className="w-full">
          <CardBody className="text-center">
            <div className="mx-auto mb-4 grid size-11 place-items-center rounded-full bg-success-subtle text-success">
              <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
                <path d="m4 12 5 5L20 6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <h1 className="text-lg font-semibold text-text">Check your email</h1>
            <p className="mt-1.5 text-sm text-muted">
              If <span className="font-medium text-text">{email}</span> can be
              registered, a confirmation link is on its way.
            </p>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md items-center px-4 py-12">
      <div className="w-full">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          Create your account
        </h1>
        <p className="mt-1.5 text-sm text-muted">Free, and takes a moment.</p>

        <Card className="mt-6">
          <CardBody>
            <form onSubmit={onSubmit} className="grid gap-4" noValidate>
              {error ? <Alert tone="danger">{error}</Alert> : null}
              <Field
                label="Full name"
                autoComplete="name"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                hint="Printed on your certificate."
              />
              <Field
                label="Email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <Field
                label="Password"
                type="password"
                autoComplete="new-password"
                required
                minLength={MIN_PASSWORD}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                hint={`At least ${MIN_PASSWORD} characters.`}
              />
              <Button type="submit" loading={loading} className="mt-1 w-full">
                Create account
              </Button>
            </form>

            <div className="mt-4 grid gap-4">
              <AuthDivider />
              {/* No email to confirm and no password to choose, so this is the
                  shorter path -- but it is second, because the form above is
                  the one that works without a Google account. */}
              <GoogleButton label="Sign up with Google" />
            </div>
          </CardBody>
        </Card>

        <p className="mt-5 text-center text-sm text-muted">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
