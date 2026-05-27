import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend port — overridable via env so local dev can sidestep a port-8000
// collision without editing source. Defaults match start_all.py / Dockerfile.
const BACKEND_PORT = process.env.BACKEND_PORT || '8000'
const PROXY_TARGET = `http://localhost:${BACKEND_PORT}`

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    // Vite's `allowedHosts` exists to block DNS rebinding attacks against
    // the dev server. This app is only ever exposed inside trusted
    // networks (localhost, a private tailnet, or an explicitly-set-up
    // tunnel) — never on the public internet without an upstream proxy.
    // `true` lets any Host header through, which means tailnet short names
    // (e.g. http://agent-smith-02:3000), tailnet FQDNs, Tailscale Funnel,
    // Cloudflare Tunnel, and `docker compose` deploys all just work
    // without a per-deploy vite config edit.
    allowedHosts: true,
    proxy: {
      '/api': {
        target: PROXY_TARGET,
        changeOrigin: true
      },
      '/static': {
        target: PROXY_TARGET,
        changeOrigin: true
      }
    }
  }
})

