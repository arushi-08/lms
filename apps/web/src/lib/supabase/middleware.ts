import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { env } from "@/lib/env";

const PROTECTED = ["/dashboard", "/learn", "/admin"];

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
    // Send them back where they were headed after signing in, but only ever to
    // a path on this site — an absolute URL here would be an open redirect.
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  return response;
}
