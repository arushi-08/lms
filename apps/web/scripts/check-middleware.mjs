#!/usr/bin/env node
/**
 * Asserts the middleware matcher still covers every path that needs a session
 * check, and still skips the ones that must not get one.
 *
 * The matcher is a single negative-lookahead regex. Adding one exclusion to it
 * is a two-character edit that can silently stop `/dashboard` being guarded,
 * and nothing about the app looks different afterwards — pages render, tests
 * pass, and the only symptom is that signed-out visitors can reach them. The
 * regex is read out of the real file so this cannot drift from what ships.
 *
 *   node scripts/check-middleware.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SOURCE = readFileSync(join(HERE, "..", "src", "middleware.ts"), "utf8");

const found = SOURCE.match(/matcher:\s*\[\s*(?:\/\/[^\n]*\n\s*)*"((?:[^"\\]|\\.)*)"/);
if (!found) {
  console.error("FAIL could not find the matcher pattern in src/middleware.ts");
  process.exit(1);
}

// The file is TypeScript source, so backslashes are doubled there. Undo one
// level to get the pattern Next actually compiles.
const pattern = found[1].replace(/\\\\/g, "\\");
const matcher = new RegExp(`^${pattern}$`);

/** Paths the middleware must run on: these are the ones it guards. */
const MUST_MATCH = [
  ["/dashboard", "a student's own page"],
  ["/dashboard/", "trailing slash"],
  ["/admin", "the admin area"],
  ["/admin/courses", "deeper in the admin area"],
  ["/admin/courses/abc-123", "a dynamic admin route"],
  ["/account/security", "two-factor setup"],
  ["/account/verify", "the step-up challenge"],
  ["/learn/pilot-course/lesson-id", "a lesson"],
  ["/", "the catalog, which renders differently when signed in"],
  ["/login", "so an already-signed-in visitor is recognised"],
  ["/courses/pilot-course", "a course page"],
];

/** Paths the middleware must skip. */
const MUST_SKIP = [
  ["/auth/callback", "mid-PKCE exchange; it owns its own cookies"],
  ["/auth/signout", "removing the session on purpose"],
  ["/_next/static/chunk.js", "a build asset"],
  ["/_next/image", "the image optimiser"],
  ["/favicon.ico", "an icon"],
  ["/icon.svg", "an icon"],
  ["/logo.png", "an image"],
  ["/font.woff2", "a font"],
];

let failed = 0;
const fail = (m) => {
  console.error(`FAIL ${m}`);
  failed++;
};

for (const [path, why] of MUST_MATCH) {
  if (!matcher.test(path)) fail(`${path} is NOT guarded (${why})`);
}
for (const [path, why] of MUST_SKIP) {
  if (matcher.test(path)) fail(`${path} IS guarded but should be skipped (${why})`);
}

// The guard list and the protected-prefix list have to agree: a prefix the
// middleware redirects on is useless if the matcher never runs there.
const protectedList = SOURCE.includes("updateSession")
  ? readFileSync(join(HERE, "..", "src", "lib", "supabase", "middleware.ts"), "utf8")
  : "";
const prefixes = [...protectedList.matchAll(/"(\/[a-z-]+)"/g)].map((m) => m[1]);
for (const prefix of prefixes) {
  if (!matcher.test(prefix)) {
    fail(`${prefix} is in PROTECTED but the matcher does not run there`);
  }
}

if (failed) {
  console.error(`\n${failed} middleware check(s) failed.`);
  process.exit(1);
}
console.log(
  `Middleware matcher OK (${MUST_MATCH.length} guarded, ${MUST_SKIP.length} skipped, ` +
    `${prefixes.length} protected prefixes reachable).`,
);
