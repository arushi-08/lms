/** Types for safe-next.mjs, which is plain ESM so a Node script can import it too. */
export declare const DEFAULT_NEXT: string;
export declare function safeNextPath(raw: string | null | undefined, fallback?: string): string;
export declare function safeNextUrl(
  raw: string | null | undefined,
  origin: string,
  fallback?: string,
): URL;
