/**
 * Server-side calls to the FastAPI backend, carrying the caller's own token.
 *
 * Deliberately forwards the *user's* access token rather than using any
 * elevated credential. The backend re-checks the role on every admin route, so
 * the browser and the server reach exactly the same authorisation decision and
 * there is one place to get it right.
 */
import { apiFetch } from "@/lib/api";
import { createClient } from "@/lib/supabase/server";

export async function accessToken(): Promise<string | null> {
  const supabase = await createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

export async function apiGet<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { accessToken: await accessToken() });
}
