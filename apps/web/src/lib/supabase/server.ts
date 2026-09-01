import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";

import { env } from "@/lib/env";

/**
 * Server client, backed by httpOnly cookies rather than localStorage.
 *
 * This is the reason the app is Next rather than a plain SPA: a token in
 * localStorage is readable by any XSS on the page, while an httpOnly cookie
 * is not.
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
          // Server Components cannot set cookies. Harmless: middleware
          // refreshes the session on every request, so the write that matters
          // has already happened there.
        }
      },
    },
  });
}
