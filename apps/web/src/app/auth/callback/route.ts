import { NextResponse } from "next/server";

import { safeNextUrl } from "@/lib/safe-next";
import { createClient } from "@/lib/supabase/server";

/**
 * Exchanges a one-time code for a session, then lands the user somewhere useful.
 *
 * Two flows arrive here and both hand over a `code`: the emailed confirmation or
 * recovery link, and the Google OAuth redirect. The exchange is identical, which
 * is why there is one route rather than two.
 *
 * Nothing the provider sends is echoed back to the page. `error_description`
 * comes from outside this application, and reflecting it -- even into a
 * framework that escapes HTML -- makes an attacker the author of text our own
 * login page presents as its own. A fixed code is enough for the user; the
 * detail belongs in the server log.
 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const providerError = url.searchParams.get("error");
  const next = url.searchParams.get("next");

  if (providerError) {
    console.warn(
      `[auth:callback] provider refused: ${providerError} ` +
        `(${url.searchParams.get("error_description") ?? "no description"})`,
    );
    return NextResponse.redirect(new URL("/login?error=oauth", url.origin));
  }

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    // A safe in-site path or the dashboard -- never a URL from the query string.
    if (!error) return NextResponse.redirect(safeNextUrl(next, url.origin));
    console.warn(`[auth:callback] code exchange failed: ${error.message}`);
  }

  return NextResponse.redirect(new URL("/login?error=link", url.origin));
}
