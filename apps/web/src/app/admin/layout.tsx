import { redirect } from "next/navigation";

import { createClient } from "@/lib/supabase/server";

/**
 * Gate for the whole admin area.
 *
 * This is the third check, not the only one: middleware requires a session,
 * this requires the admin role, and the API re-reads the role on every request.
 * The UI guard exists so a student never sees a broken page; the API guard is
 * what actually protects the data.
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

  const { data: profile } = await supabase
    .from("profiles")
    .select("role")
    .eq("id", user.id)
    .single();

  // Not a 403 page: a student has no business knowing an admin area is here.
  if (profile?.role !== "admin") redirect("/dashboard");

  return <>{children}</>;
}
