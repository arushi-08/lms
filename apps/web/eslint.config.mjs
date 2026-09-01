// Flat config. Next 16 removed `next lint` and eslint-config-next now ships
// flat configs directly, so there is no FlatCompat shim here — the previous
// compat-based config threw a schema error rather than linting anything.
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

export default [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...coreWebVitals,
  ...typescript,
];
