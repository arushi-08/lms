"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { reportAuthError } from "@/lib/auth-errors";
import { createClient } from "@/lib/supabase/client";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(
    params.get("error") === "link" ? "That link has expired. Sign in instead." : null,
  );
  const [loading, setLoading] = useState(false);

  // Only ever an in-site path: an absolute value here would let a crafted link
  // bounce someone to another site straight after they sign in.
  const rawNext = params.get("next") ?? "/dashboard";
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/dashboard";

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);

    const supabase = createClient();
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (signInError) {
      // Generic message to the user, real reason to the dev console.
      setError(reportAuthError("signIn", signInError));
      setLoading(false);
      return;
    }

    router.push(next);
    router.refresh();
  }

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md items-center px-4 py-12">
      <div className="w-full">
        <h1 className="text-2xl font-semibold tracking-tight text-text">
          Welcome back
        </h1>
        <p className="mt-1.5 text-sm text-muted">Sign in to continue learning.</p>

        <Card className="mt-6">
          <CardBody>
            <form onSubmit={onSubmit} className="grid gap-4" noValidate>
              {error ? <Alert tone="danger">{error}</Alert> : null}
              <Field
                label="Email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
              <div className="grid gap-1.5">
                <Field
                  label="Password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <Link
                  href="/forgot-password"
                  className="justify-self-end text-xs font-medium text-muted hover:text-accent hover:underline"
                >
                  Forgot your password?
                </Link>
              </div>
              <Button type="submit" loading={loading} className="mt-1 w-full">
                Sign in
              </Button>
            </form>
          </CardBody>
        </Card>

        <p className="mt-5 text-center text-sm text-muted">
          No account?{" "}
          <Link href="/signup" className="font-medium text-accent hover:underline">
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
