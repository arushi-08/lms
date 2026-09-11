import { Suspense } from "react";

import { VerifyForm } from "./verify-form";

export const metadata = { title: "Enter your code" };

export default async function VerifyPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;
  // Validated in the client component, not trusted here: one guard, in the
  // module that documents every way the value can be spelled.
  return (
    <Suspense>
      <VerifyForm next={next ?? "/admin"} />
    </Suspense>
  );
}
