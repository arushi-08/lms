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

function logAuthError(context: string, error: unknown): void {
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
}

export function reportAuthError(context: string, error: unknown): string {
  logAuthError(context, error);
  return GENERIC_SIGN_IN_MESSAGE;
}

/** Supabase's machine-readable error code, when it sent one. */
function errorCode(error: unknown): string {
  const code = (error as { code?: unknown } | null)?.code;
  return typeof code === "string" ? code : "";
}

/**
 * Signup is not sign-in, and must not borrow its message.
 *
 * Two failures pull in opposite directions here. Repeating Supabase's own text
 * leaks "User already registered", which is the enumeration problem again. But a
 * single blank "something went wrong" hides what the user can actually fix — a
 * password the server considers weak, an address that does not parse — and
 * leaves them retyping the same form with no idea what is wrong.
 *
 * So: a short list of causes that are safe to name because each describes the
 * input just typed rather than what is already in the database, and a generic
 * message for everything else.
 *
 * `alreadyRegistered` is neither. The caller should treat it exactly like
 * success and show the "check your email" screen — Supabase emails the real
 * owner in that case, and saying anything else on the page would confirm the
 * address is registered here.
 */
export function describeSignUpError(error: unknown): {
  message: string;
  alreadyRegistered: boolean;
} {
  logAuthError("signUp", error);

  switch (errorCode(error)) {
    case "user_already_exists":
    case "email_exists":
      return { message: "", alreadyRegistered: true };
    case "weak_password":
      return {
        message: "That password is too easy to guess. Try a longer one.",
        alreadyRegistered: false,
      };
    case "email_address_invalid":
    case "validation_failed":
      return {
        message: "That email address does not look right.",
        alreadyRegistered: false,
      };
    case "over_email_send_rate_limit":
    case "over_request_rate_limit":
      return {
        message: "Too many attempts just now. Wait a minute and try again.",
        alreadyRegistered: false,
      };
    default:
      return {
        message: "We could not create the account just now. Please try again.",
        alreadyRegistered: false,
      };
  }
}
