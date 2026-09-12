#!/usr/bin/env node
/**
 * Asserts every text/background pair the app actually renders clears WCAG AA.
 *
 * This exists because a palette is easy to choose and hard to keep honest. The
 * brief for this one names Emerald `#059669` for achievement and amber `#D97706`
 * for pending — both correct as *fills*, and both under 3.5:1 on white, so used
 * as text they are decorative rather than readable. The fix is not to abandon
 * the brief's colours but to know which role each value is fit for, and a number
 * is the only way to know that.
 *
 * Reads the tokens straight out of globals.css, so it checks the palette that
 * ships rather than a copy of it that can drift.
 *
 *   node scripts/check-contrast.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSS = readFileSync(join(HERE, "..", "src", "app", "globals.css"), "utf8");

/** WCAG AA: 4.5:1 for body text, 3:1 for large text and UI boundaries. */
const AA_TEXT = 4.5;
const AA_LARGE = 3.0;
/** Non-text contrast (borders, focus rings, meter fills) — WCAG 1.4.11. */
const AA_UI = 3.0;

/* --- reading the tokens ---------------------------------------------------- */

/**
 * Tokens are declared in three blocks: `:root` (light), `[data-theme="dark"]`
 * and `@theme inline` (the Tailwind mapping, which holds no colours of its own).
 * Only the first two matter here.
 */
function tokensIn(blockStart) {
  const start = CSS.indexOf(blockStart);
  if (start === -1) throw new Error(`no ${blockStart} block in globals.css`);
  const open = CSS.indexOf("{", start);
  const end = CSS.indexOf("\n}", open);
  const body = CSS.slice(open, end);

  const found = {};
  for (const [, name, value] of body.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
    found[name] = value.trim();
  }
  return found;
}

const light = tokensIn(":root {");
const dark = { ...light, ...tokensIn('[data-theme="dark"] {') };

/** Resolve a token to a hex string, following `var(--other)` indirection. */
function resolve(tokens, name, seen = new Set()) {
  if (seen.has(name)) throw new Error(`--${name} resolves in a circle`);
  seen.add(name);

  const raw = tokens[name];
  if (raw === undefined) throw new Error(`--${name} is not defined`);

  const indirect = raw.match(/^var\(--([a-z0-9-]+)\)$/);
  if (indirect) return resolve(tokens, indirect[1], seen);

  if (/^#[0-9a-f]{6}$/i.test(raw)) return raw.toLowerCase();
  throw new Error(
    `--${name} is "${raw}" — this check only understands 6-digit hex and var() ` +
      `indirection. If a token has to be another format, exclude it explicitly ` +
      `rather than letting it fall through unchecked.`,
  );
}

/* --- the contrast maths (WCAG 2.x relative luminance) ---------------------- */

function channel(eight) {
  const c = eight / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function luminance(hex) {
  const n = Number.parseInt(hex.slice(1), 16);
  return (
    0.2126 * channel((n >> 16) & 255) +
    0.7152 * channel((n >> 8) & 255) +
    0.0722 * channel(n & 255)
  );
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/* --- what to check --------------------------------------------------------- */

/**
 * Every pair is one the app renders. Adding a coloured-text-on-coloured-ground
 * combination to a component means adding it here, or it is unverified.
 */
const PAIRS = [
  // Body copy, on both grounds it appears on.
  ["text", "bg", AA_TEXT, "body text on the page background"],
  ["text", "surface", AA_TEXT, "body text on a card"],
  ["text", "surface-sunken", AA_TEXT, "body text on a sunken panel"],
  ["text", "surface-hover", AA_TEXT, "body text on a hovered row"],

  // Secondary copy. Still prose, so still 4.5 — "muted" is not a licence to be
  // unreadable, it is a licence to be quieter.
  ["text-muted", "bg", AA_TEXT, "secondary text on the page background"],
  ["text-muted", "surface", AA_TEXT, "secondary text on a card"],
  ["text-muted", "surface-hover", AA_TEXT, "secondary text on a hovered row"],

  // Placeholders and hints: large-text threshold, because they are never the
  // only way to understand a field and they must not read as filled-in values.
  ["text-subtle", "surface", AA_LARGE, "placeholder text in an input"],

  // The primary button and links.
  ["text-on-accent", "accent", AA_TEXT, "label on a primary button"],
  ["text-on-accent", "accent-hover", AA_TEXT, "label on a hovered primary button"],
  ["accent", "bg", AA_TEXT, "a link on the page background"],
  ["accent", "surface", AA_TEXT, "a link on a card"],
  ["accent", "accent-subtle", AA_TEXT, "accent text on its own tint"],

  // Status text sits on its own tint (see the Alert and Badge components).
  ["success", "success-subtle", AA_TEXT, "success text in an alert"],
  ["warning", "warning-subtle", AA_TEXT, "warning text in an alert"],
  ["danger", "danger-subtle", AA_TEXT, "danger text in an alert"],
  ["info", "info-subtle", AA_TEXT, "info text in an alert"],
  // …and status text also appears bare, as a label beside a lesson.
  ["success", "surface", AA_TEXT, "a 'completed' label on a card"],
  ["warning", "surface", AA_TEXT, "a 'pending' label on a card"],
  ["danger", "surface", AA_TEXT, "an error label on a card"],

  // The structural navigation, which is dark in both themes.
  ["nav-text", "nav", AA_TEXT, "navigation text on the nav bar"],
  ["nav-muted", "nav", AA_TEXT, "secondary navigation text on the nav bar"],
  ["nav-text", "nav-hover", AA_TEXT, "navigation text on a hovered item"],
  ["accent-on-nav", "nav", AA_TEXT, "the active nav item"],

  // Non-text: a border nobody can see is not separating anything, and a focus
  // ring nobody can see fails keyboard users specifically.
  ["border-strong", "bg", AA_UI, "a card border against the page"],
  ["border-strong", "surface", AA_UI, "a divider inside a card"],
  ["focus", "bg", AA_UI, "the focus ring on the page background"],
  ["focus", "surface", AA_UI, "the focus ring on a card"],
  ["accent", "surface-sunken", AA_UI, "a progress bar against its track"],
  ["success", "surface-sunken", AA_UI, "a completed progress bar against its track"],
];

/* --- run ------------------------------------------------------------------- */

let failures = 0;
const rows = [];

for (const [themeName, tokens] of [
  ["light", light],
  ["dark", dark],
]) {
  for (const [fg, bg, required, description] of PAIRS) {
    let got;
    try {
      got = ratio(resolve(tokens, fg), resolve(tokens, bg));
    } catch (error) {
      console.error(`FAIL [${themeName}] ${description}: ${error.message}`);
      failures++;
      continue;
    }
    const ok = got >= required;
    if (!ok) failures++;
    rows.push({ themeName, fg, bg, got, required, description, ok });
  }
}

const width = Math.max(...rows.map((r) => r.description.length));
for (const r of rows) {
  const mark = r.ok ? "ok  " : "FAIL";
  const line =
    `${mark} [${r.themeName.padEnd(5)}] ${r.description.padEnd(width)}  ` +
    `${r.got.toFixed(2)}:1 (needs ${r.required})  --${r.fg} on --${r.bg}`;
  if (r.ok) {
    if (process.env.VERBOSE) console.log(line);
  } else {
    console.error(line);
  }
}

if (failures) {
  console.error(
    `\n${failures} contrast check(s) failed. ` +
      `Darken the foreground or lighten the ground — do not lower the threshold.`,
  );
  process.exit(1);
}
console.log(
  `Contrast OK (${rows.length} pairs across light and dark, WCAG AA). ` +
    `Set VERBOSE=1 to see the numbers.`,
);
