"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Sentry goes here once it is wired up.
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md flex-col items-center justify-center px-4 text-center">
      <h1 className="text-2xl font-semibold tracking-tight text-text">
        Something went wrong
      </h1>
      <p className="mt-2 text-sm text-muted">
        This one is on us. Try again, and if it keeps happening let us know.
      </p>
      {error.digest ? (
        <p className="mt-3 font-mono text-xs text-subtle">ref {error.digest}</p>
      ) : null}
      <Button onClick={reset} variant="secondary" className="mt-6">
        Try again
      </Button>
    </div>
  );
}
