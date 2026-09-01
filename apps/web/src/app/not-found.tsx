import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[calc(100dvh-3.5rem)] max-w-md flex-col items-center justify-center px-4 text-center">
      <p className="text-sm font-medium text-accent">404</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-text">
        We could not find that page
      </h1>
      <p className="mt-2 text-sm text-muted">
        The link may be out of date, or the course may no longer be published.
      </p>
      <Link href="/" className="mt-6">
        <Button variant="secondary">Back to courses</Button>
      </Link>
    </div>
  );
}
