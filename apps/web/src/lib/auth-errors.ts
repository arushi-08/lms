/**
 * Auth failures: one message for users, the real reason for developers.
 *
 * The UI must not distinguish "no such account" from "wrong password" — that
 * difference turns the login form into a tool for checking which email
 * addresses are registered here.
 *
 * But hiding the cause from the *developer* protects nobody. Supabase already
 * returns its real error in the HTTP response, visible in the Network tab, so
 * logging it to the console in development reveals nothing an attacker could
 * not already read. It just saves an hour of guessing.
 */
const GENERIC_SIGN_IN_MESSAGE = "That email and password do not match an account.";

export function reportAuthError(context: string, error: unknown): string {
  if (process.env.NODE_ENV !== "production") {
    const detail =
      error instanceof Error
        ? `${error.name}: ${error.message}`
        : JSON.stringify(error);
    console.error(
      `[auth:${context}] ${detail}\n` +
        "  (shown to the user as a deliberately generic message; " +
        "this line only appears in development)",
    );
  }
  return GENERIC_SIGN_IN_MESSAGE;
}
