/**
 * Turn backend error codes (snake_case like `invalid_credentials`) into
 * clear, human sentences. Unknown codes fall back to a de-underscored,
 * sentence-cased version so a raw `foo_bar` never reaches the user.
 */
const MESSAGES: Record<string, string> = {
  invalid_credentials: "That email and password don't match. Please try again.",
  invalid_email: "Please enter a valid email address.",
  email_required: "Please enter your email address.",
  password_required: "Please enter your password.",
  email_already_exists: "An account with this email already exists. Try signing in instead.",
  email_taken: "An account with this email already exists. Try signing in instead.",
  user_exists: "An account with this email already exists. Try signing in instead.",
  weak_password: "Please choose a stronger password (at least 8 characters).",
  password_too_short: "Your password must be at least 8 characters.",
  passwords_do_not_match: "The two passwords don't match.",
  email_not_verified: "Please verify your email address before signing in — check your inbox.",
  account_disabled: "This account has been disabled. Contact support@credyx.ai.",
  account_locked: "Too many attempts. Please wait a few minutes and try again.",
  auth_required: "Please sign in to continue.",
  forbidden: "You don't have access to that.",
  not_found: "We couldn't find what you were looking for.",
  invalid_token: "This link is invalid or has expired. Please request a new one.",
  token_expired: "This link has expired. Please request a new one.",
  rate_limited: "Too many requests. Please slow down and try again shortly.",
  too_many_requests: "Too many requests. Please slow down and try again shortly.",
  internal_error: "Something went wrong on our end. Please try again.",
  server_error: "Something went wrong on our end. Please try again.",
  not_implemented: "This isn't available yet.",
};

const CODE_RE = /^[a-z0-9]+(?:_[a-z0-9]+)+$/;

export function humanizeError(
  raw: string | null | undefined,
  fallback = "Something went wrong. Please try again.",
): string {
  if (!raw) return fallback;
  const key = raw.trim().toLowerCase();
  if (MESSAGES[key]) return MESSAGES[key];

  // Looks like a bare error code (snake_case, no spaces) → prettify it so the
  // user never sees underscores, e.g. "invalid_email" → "Invalid email".
  if (CODE_RE.test(key)) {
    const words = key.replace(/_/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1) + ".";
  }

  // Already a human sentence (has spaces / punctuation) → show as-is.
  return raw.trim();
}
