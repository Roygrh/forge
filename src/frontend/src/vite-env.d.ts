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
