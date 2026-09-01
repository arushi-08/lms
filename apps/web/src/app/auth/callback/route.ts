import { NextResponse } from "next/server";

import { createClient } from "@/lib/supabase/server";

/** Exchanges the emailed code for a session, then lands the user somewhere useful. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = url.searchParams.get("next") ?? "/dashboard";

  // Only ever redirect within this site. Accepting an absolute URL here would
  // make the confirmation link an open redirect, which is a phishing gift.
  const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(new URL(safeNext, url.origin));
  }

  return NextResponse.redirect(new URL("/login?error=link", url.origin));
}
