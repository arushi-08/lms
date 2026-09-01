import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { createClient } from "@/lib/supabase/server";

import { ResetPasswordForm } from "./reset-password-form";

export const metadata = { title: "Choose a new password" };

export default async function ResetPasswordPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // Arriving here without a session means the recovery link was already used,
  // has expired, or was opened in a different browser from the one that
  // requested it — the PKCE verifier is stored per browser. Say so plainly
  // rather than showing a form that cannot work.
  if (!user) {
    return (
      <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md items-center px-4 py-12">
        <Card className="w-full">
          <CardBody className="text-center">
            <h1 className="text-lg font-semibold text-text">
              This reset link is no longer valid
            </h1>
            <p className="mt-1.5 text-sm text-muted">
              Links expire after an hour, can only be used once, and must be
              opened in the same browser that requested them.
            </p>
            <Link href="/forgot-password" className="mt-5 inline-block">
              <Button size="sm">Request a new link</Button>
            </Link>
          </CardBody>
        </Card>
      </div>
    );
  }

  return <ResetPasswordForm email={user.email ?? ""} />;
}
