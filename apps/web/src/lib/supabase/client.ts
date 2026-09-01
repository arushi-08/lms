import { createBrowserClient } from "@supabase/ssr";

import { env } from "@/lib/env";

/**
 * Browser client. Carries the anon key, which is public by design — every
 * query it makes is still subject to RLS.
 */
export function createClient() {
  return createBrowserClient(env.supabaseUrl, env.supabaseAnonKey);
}
