import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { env } from "@/lib/env";
import { safeNextPath } from "@/lib/safe-next";

// /account included: the security and step-up pages belong to a signed-in user,
// and they sit outside /admin so a blocked admin can actually reach them.
const PROTECTED = ["/dashboard", "/learn", "/admin", "/account"];

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(env.supabaseUrl, env.supabaseAnonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        for (const { name, value } of cookiesToSet) {
          request.cookies.set(name, value);
        }
        response = NextResponse.next({ request });
        for (const { name, value, options } of cookiesToSet) {
          response.cookies.set(name, value, options);
        }
      },
    },
  });

  // getUser(), not getSession(): getSession trusts the cookie's contents,
  // while getUser revalidates the token with Supabase. On a route guard the
  // difference is whether a forged cookie gets in.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;
  const needsAuth = PROTECTED.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );

  if (needsAuth && !user) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    // Send them back where they were headed after signing in, but only ever to
    // a path on this site. This one comes from our own routing rather than from
    // a query string, so it is already safe -- passing it through the same guard
    // anyway costs nothing and means there is one rule, not two.
    url.searchParams.set("next", safeNextPath(pathname));
    return NextResponse.redirect(url);
  }

  return response;
}
