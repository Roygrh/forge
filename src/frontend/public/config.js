// Runtime configuration placeholder — the development answer to the same question the
// container answers at start-up (see nginx/default.conf.template).
//
// `vite build` copies this file into dist/ and `vite dev` serves it, so index.html's
// <script src="/config.js"> is never a 404. In the container an exact-match nginx
// location answers /config.js instead, with the real values; nothing here overrides it.
// Empty values on purpose: src/api/client.ts falls back to VITE_* and then to the
// documented localhost default.
window.__FORGE_CONFIG__ = { apiBaseUrl: '', role: '' }
