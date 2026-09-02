/** Types for csp.mjs, which is plain ESM so a Node script can import it too. */
export declare const DEFAULT_API_URL: string;
export declare function apiOriginFrom(raw: string | undefined): string;
export declare function buildCsp(apiUrl: string | undefined): string;
