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
    // Tunnels (Tailscale Funnel / Cloudflare Tunnel) hit the dev server with
    // a non-localhost Host header; vite rejects those by default. Allow the
    // tailnet domain so `tailscale funnel 3000` works without 403.
    allowedHosts: ['.ts.net'],
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

