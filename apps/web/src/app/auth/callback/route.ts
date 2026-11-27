import { NextResponse } from "next/server";

import { safeNextUrl } from "@/lib/safe-next";
import { createRouteHandlerClient } from "@/lib/supabase/server";

/**
 * Exchanges a one-time code for a session, then lands the user somewhere useful.
 *
 * Two flows arrive here and both hand over a `code`: the emailed confirmation
 * or recovery link, and the Google OAuth redirect. The exchange is identical,
 * which is why there is one route rather than two. They are told apart only so
 * that a failure says the right thing — "that link has expired" is actively
 * misleading to someone who just came back from Google.
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
  // Set by the Google button on the way out, so it comes back to us. Our own
  // marker rather than a guess from the shape of the request.
  const failure = url.searchParams.get("flow") === "oauth" ? "oauth" : "link";

  if (providerError) {
    console.warn(
      `[auth:callback] provider refused: ${providerError} ` +
        `(${url.searchParams.get("error_description") ?? "no description"})`,
    );
    return NextResponse.redirect(new URL("/login?error=oauth", url.origin));
  }

  if (!code) {
    console.warn("[auth:callback] no code and no error in the callback URL");
    return NextResponse.redirect(new URL(`/login?error=${failure}`, url.origin));
  }

  const supabase = await createRouteHandlerClient();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);

  if (error) {
    // Code and status as well as the message: "invalid request" alone does not
    // distinguish a reused code from a missing PKCE verifier, and those need
    // opposite fixes.
    console.warn(
      `[auth:callback] code exchange failed: ${error.message} ` +
        `(code=${error.code ?? "none"}, status=${error.status ?? "none"})`,
    );
    return NextResponse.redirect(new URL(`/login?error=${failure}`, url.origin));
  }

  if (!data.session) {
    // Supabase accepted the code but handed back nothing to store. Redirecting
    // to the dashboard here would bounce straight back to the login page with
    // no explanation, which is the single most confusing way this can fail.
    console.error(
      "[auth:callback] the code exchange succeeded but returned no session; " +
        "the user will not be signed in",
    );
    return NextResponse.redirect(new URL(`/login?error=${failure}`, url.origin));
  }

  // A safe in-site path or the dashboard -- never a URL from the query string.
  return NextResponse.redirect(safeNextUrl(next, url.origin));
}
