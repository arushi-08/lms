/**
 * Re-export of the root `safe-next.mjs`, so application code imports
 * `@/lib/safe-next` and only this one file knows where the plain-ESM module
 * lives. The module itself sits at the project root, like `csp.mjs`, because a
 * Node check script has to import it without a bundler.
 */
export { DEFAULT_NEXT, safeNextPath, safeNextUrl } from "../../safe-next.mjs";
