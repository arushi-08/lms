import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

import { env } from "@/lib/env";

/**
 * Server client, backed by httpOnly cookies rather than localStorage.
 *
 * This is the reason the app is Next rather than a plain SPA: a token in
 * localStorage is readable by any XSS on the page, while an httpOnly cookie
 * is not.
 *
 * For a Route Handler use `createRouteHandlerClient` instead. The difference
 * is what happens when a cookie write fails, and it matters more than it
 * sounds -- see below.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(env.supabaseUrl, env.supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Server Components cannot set cookies. Harmless here: middleware
          // refreshes the session on every request, so the write that matters
          // has already happened there.
        }
      },
    },
  });
}

/**
 * The same client, for a Route Handler, where a cookie write is expected to
 * succeed and a failure is a real bug.
 *
 * Worth being a separate function rather than a flag, because the two contexts
 * mean genuinely different things by the same failure. In a Server Component a
 * refused write is routine. In the OAuth callback it is a sign-in that worked
 * at Supabase and then evaporated: the exchange returns no error, we redirect
 * to the dashboard, middleware finds no session and bounces the user to the
 * login page. They did everything right, they are not signed in, and nothing
 * anywhere says why. Swallowing that is how a bug becomes unfindable.
 */
export async function createRouteHandlerClient() {
  const cookieStore = await cookies();

  return createServerClient(env.supabaseUrl, env.supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        for (const { name, value, options } of cookiesToSet) {
          cookieStore.set(name, value, options);
        }
      },
    },
  });
}
