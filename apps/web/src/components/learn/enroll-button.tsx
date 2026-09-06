"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { adminFetch } from "@/lib/admin-client";

export function EnrollButton({
  slug,
  isFree,
  signedIn,
}: {
  slug: string;
  isFree: boolean;
  signedIn: boolean;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!signedIn) {
    return (
      <Link href={`/login?next=/courses/${slug}`}>
        <Button size="lg">Sign in to enrol</Button>
      </Link>
    );
  }

  if (!isFree) {
    // Payments are deferred until the provider question is settled, so say so
    // rather than showing a button that cannot work.
    return (
      <Alert tone="info">
        Paid enrolment is not available yet. Ask for access and it can be granted
        directly.
      </Alert>
    );
  }

  return (
    <div className="grid gap-3">
      {error ? <Alert tone="danger">{error}</Alert> : null}
      <div>
        <Button
          size="lg"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await adminFetch("/api/enrollments", {
                method: "POST",
                body: { course_slug: slug },
              });
              router.refresh();
            } catch (cause) {
              setError(cause instanceof Error ? cause.message : "Could not enrol.");
            } finally {
              setBusy(false);
            }
          }}
        >
          Enrol for free
        </Button>
      </div>
    </div>
  );
}
