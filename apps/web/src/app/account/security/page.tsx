import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";

import { TwoFactorManager } from "./two-factor-manager";

export const metadata = { title: "Security" };

/**
 * Deliberately outside `/admin`.
 *
 * The admin layout sends a blocked admin here, so a page under `/admin` would
 * bounce them straight back into the same check — the loop being that the page
 * which fixes the problem cannot be behind the gate the problem closes.
 */
export default async function SecurityPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/account/security");

  // Own row, so this read works at one factor. It has to: an admin who has not
  // stepped up is exactly who this page is for.
  const { data: profile } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .single();

  return (
    <div className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
      <h1 className="text-2xl font-semibold tracking-tight text-text">Security</h1>
      <p className="mt-1.5 text-sm text-muted">
        How this account proves it is you.
      </p>
      <div className="mt-6">
        <TwoFactorManager isAdmin={profile?.role === "admin"} />
      </div>
    </div>
  );
}
