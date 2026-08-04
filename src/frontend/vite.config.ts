import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server binds 0.0.0.0 so the same config serves both `npm run dev` on a
// developer's machine and the `web` container in deploy/docker-compose.yml (ADR-009).
// The browser always talks to the API directly — there is no dev proxy — so the one
// thing that varies between environments is VITE_API_BASE_URL, and CORS on the API
// is exercised in development exactly as it is in the compose stack.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
  },
})
