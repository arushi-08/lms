#!/usr/bin/env node
/**
 * Asserts the CSP permits the things the app actually needs.
 *
 * Each check corresponds to a way the app breaks silently: a blocked
 * connect-src looks like a dead backend, a blocked frame-src looks like a
 * broken video player, and neither leaves a trace on the server.
 */
import { buildCsp } from "../csp.mjs";

const cases = [
  ["http://localhost:8000", "http://localhost:8000"],
  ["http://127.0.0.1:8400", "http://127.0.0.1:8400"],
  ["https://api.example.com", "https://api.example.com"],
  ["https://api.example.com/", "https://api.example.com"],
  [undefined, "http://localhost:8000"],
  ["not a url", "http://localhost:8000"],
];

let failed = 0;
const fail = (m) => { console.error("FAIL " + m); failed++; };

for (const [input, expected] of cases) {
  const directive = buildCsp(input).split("; ").find((d) => d.startsWith("connect-src"));
  if (!directive.includes(` ${expected} `) && !directive.endsWith(` ${expected}`)) {
    fail(`connect-src for ${JSON.stringify(input)} lacks ${expected}\n     got: ${directive}`);
  }
}

const csp = buildCsp("http://localhost:8000");
const need = [
  ["connect-src", "https://*.supabase.co", "auth and direct table reads"],
  ["frame-src", "https://player.vdocipher.com", "the DRM video player"],
  ["frame-src", "https://js.stripe.com", "Stripe checkout"],
  ["script-src", "https://js.stripe.com", "the Stripe SDK"],
];
for (const [directive, value, why] of need) {
  const found = csp.split("; ").find((d) => d.startsWith(directive));
  if (!found || !found.includes(value)) fail(`${directive} is missing ${value} (${why})`);
}

for (const directive of ["frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'"]) {
  if (!csp.includes(directive)) fail(`the policy no longer sets ${directive}`);
}

// unsafe-eval belongs in development only. React needs it for dev tooling;
// shipping it would weaken script-src for everyone.
if (!buildCsp("http://localhost:8000", { dev: true }).includes("'unsafe-eval'")) {
  fail("development builds need 'unsafe-eval' or React dev mode breaks");
}
if (buildCsp("https://api.example.com").includes("'unsafe-eval'")) {
  fail("'unsafe-eval' must never reach a production build");
}

// The mock provider streams video from the API origin.
const media = csp.split("; ").find((d) => d.startsWith("media-src"));
if (!media.includes("http://localhost:8000")) {
  fail("media-src must allow the API origin, or mock playback is blocked");
}

console.log(failed ? `\n${failed} CSP problem(s)` : "CSP checks passed");
process.exit(failed ? 1 : 0);
