/// <reference types="vite/client" />

/**
 * The environment this SPA reads, typed.
 *
 * Vite's own `ImportMetaEnv` carries an `any` index signature; declaring the two
 * variables Forge actually uses narrows them to `string | undefined`, so `strict`
 * forces the fallbacks in `api/client.ts` to be written rather than assumed.
 */
interface ImportMetaEnv {
  /** Base URL of the Forge API as the browser sees it, e.g. http://localhost:8000 */
  readonly VITE_API_BASE_URL?: string
  /** Demonstration role sent as X-Forge-Role (NFR-5): configurator | approver | viewer */
  readonly VITE_FORGE_ROLE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/**
 * Configuration handed to the SPA by whatever is *serving* it, at page load.
 *
 * Vite inlines `VITE_*` when the bundle is built, which would make the production image
 * environment-specific — the thing ADR-009 says these images must not be. So the
 * container serves `/config.js` at start-up instead (`nginx/default.conf.template`) and
 * the fields below arrive from the environment rather than from the build.
 *
 * Every field is optional and may be an empty string: the placeholder served in
 * development sets both to `''`, and `src/api/client.ts` falls back to `VITE_*` and then
 * to the documented default. A missing value must never leave the SPA pointing nowhere.
 */
interface ForgeRuntimeConfig {
  /** Base URL of the Forge API as the browser sees it, e.g. http://localhost:8000 */
  readonly apiBaseUrl?: string
  /** Demonstration role sent as X-Forge-Role (NFR-5): configurator | approver | viewer */
  readonly role?: string
}

interface Window {
  readonly __FORGE_CONFIG__?: ForgeRuntimeConfig
}
