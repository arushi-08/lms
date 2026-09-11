import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";

/**
 * Gate for the whole admin area.
 *
 * The fourth check, not the only one: middleware requires a session, this
 * requires the admin role *and* a second factor, the API re-checks both on every
 * request, and RLS refuses admin reads to a token that is not aal2.
 *
 * What this one is for is the experience. Without it, an admin who has not
 * stepped up would watch the panel render and then every request inside it fail
 * with a 403 — the data safe, the page apparently broken. Redirecting is not the
 * protection; the API and RLS are.
 */
export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/admin");

  // Own row, readable at one factor -- which matters, because an admin who has
  // not stepped up has to get past this line to be sent somewhere useful.
  const { data: profile } = await supabase
    .from("profiles")
    .select("role, mfa_factor_id, mfa_verified_factors")
    .eq("id", user.id)
    .single();

  // Not a 403 page: a student has no business knowing an admin area is here.
  if (profile?.role !== "admin") redirect("/dashboard");

  // No trusted authenticator yet, or the account's factors no longer match the
  // one it was set up with. Both need the security page. The comparison mirrors
  // the API's, which is the one that decides.
  const pinned: string | null = profile.mfa_factor_id;
  const verified: string[] = profile.mfa_verified_factors ?? [];
  const matchesPin = pinned !== null && verified.length === 1 && verified[0] === pinned;
  if (!matchesPin) redirect("/account/security");

  // Enrolled and consistent, but this session has not presented a code.
  const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
  if (aal?.currentLevel !== "aal2") redirect("/account/verify?next=/admin");

  return <>{children}</>;
}
