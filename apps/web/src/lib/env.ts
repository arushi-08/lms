/**
 * Environment access with a fail-fast check.
 *
 * A missing Supabase URL should stop the build with a clear message, not
 * produce a page that renders fine and fails silently on the first login.
 */
function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `${name} is not set. Copy .env.example to .env.local and fill it in.`,
    );
  }
  return value;
}

export const env = {
  supabaseUrl: required(
    "NEXT_PUBLIC_SUPABASE_URL",
    process.env.NEXT_PUBLIC_SUPABASE_URL,
  ),
  supabaseAnonKey: required(
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  ),
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
};
