#!/usr/bin/env node
/**
 * Asserts the post-sign-in redirect guard rejects every way of naming another
 * host, and still accepts an ordinary in-site path.
 *
 * Worth its own check because the failure is silent and expensive: an open
 * redirect on a login page is not a broken page, it is a working phishing
 * chain. The `/\evil.com` case below was a real hole in this app.
 */
import { DEFAULT_NEXT, safeNextPath, safeNextUrl } from "../safe-next.mjs";

const ORIGIN = "https://lms.example.com";

const mustReject = [
  ["https://evil.com", "an absolute URL"],
  ["http://evil.com", "an absolute URL, plain http"],
  ["//evil.com", "protocol-relative"],
  ["/\\evil.com", "backslash reads as a second slash in the URL parser"],
  ["/\\/evil.com", "backslash then slash"],
  ["\\\\evil.com", "UNC-looking, no leading slash"],
  ["/\tevil.com", "tab, which browsers strip"],
  ["/\nevil.com", "newline, which browsers strip"],
  ["/ /evil.com", "space, which resolves oddly"],
  ["javascript:alert(1)", "a script URL"],
  ["data:text/html,<h1>x", "a data URL"],
  ["dashboard", "no leading slash, resolves relative to the current page"],
  ["", "empty"],
  [null, "absent"],
  [undefined, "absent"],
  [42, "not a string at all"],
];

const mustAccept = [
  "/dashboard",
  "/learn/pilot-course/abc",
  "/courses/slug?tab=modules",
  "/admin",
  "/dashboard#certificates",
];

let failed = 0;
const fail = (m) => {
  console.error(`FAIL ${m}`);
  failed++;
};

for (const [value, why] of mustReject) {
  const got = safeNextPath(value);
  if (got !== DEFAULT_NEXT) {
    fail(`${JSON.stringify(value)} (${why}) should fall back, got ${JSON.stringify(got)}`);
    continue;
  }
  // The resolved URL is what actually reaches the browser, so check that too:
  // a guard that returns a safe string but is used with an unsafe one is no
  // guard at all.
  const url = safeNextUrl(value, ORIGIN);
  if (url.origin !== ORIGIN) {
    fail(`${JSON.stringify(value)} (${why}) resolved off-origin to ${url.href}`);
  }
}

for (const value of mustAccept) {
  const got = safeNextPath(value);
  if (got !== value) {
    fail(`${JSON.stringify(value)} is an ordinary in-site path, got ${JSON.stringify(got)}`);
  }
  if (safeNextUrl(value, ORIGIN).origin !== ORIGIN) {
    fail(`${JSON.stringify(value)} resolved off-origin`);
  }
}

// A caller may supply its own fallback; it must be used, and must itself be
// safe -- otherwise the fallback becomes the way in.
if (safeNextPath("//evil.com", "/admin") !== "/admin") fail("custom fallback ignored");

if (failed) {
  console.error(`\n${failed} redirect check(s) failed.`);
  process.exit(1);
}
console.log(`Redirect guard OK (${mustReject.length} rejected, ${mustAccept.length} accepted).`);
