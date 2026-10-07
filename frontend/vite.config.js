import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'

const BACKEND = process.env.VITE_BACKEND || 'https://erp.pranera.in'

export default defineConfig(({ command }) => ({
  base: command === 'serve' ? '/' : '/assets/pranera_roll/roll_app/',

  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') }
  },

  server: {
    port: 3000,
    // Dev-server only — vite build never reads this (production always talks
    // to erp.pranera.in directly since it's served from that same origin).
    // Needed so `npm run dev` (localhost:3000) can reach the live backend;
    // without it every /api/* call 404s against Vite's own dev server and
    // returns HTML instead of JSON.
    proxy: command === 'serve' ? {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        secure: false,
        ws: true,
        cookieDomainRewrite: 'localhost',
        headers: {
          'Origin': BACKEND,
          'Referer': BACKEND
        },
        // Frappe marks its session cookie (sid) as Secure because
        // erp.pranera.in is HTTPS. Vite's dev server itself is plain HTTP
        // (localhost:3000), and browsers silently refuse to store *any*
        // Secure cookie over a non-HTTPS connection — no error, no warning,
        // it just never lands. cookieDomainRewrite only touches the
        // Domain= attribute, not Secure, so login would appear to succeed
        // (the login POST itself returns 200) while the session cookie
        // that request needed to persist for every call after it never
        // actually got stored. Strip Secure (dev only) so the cookie sticks.
        configure(proxy) {
          // node-http-proxy has a long-standing quirk: for POST/PUT requests
          // with no body (like our logout call — POST, no payload), it can
          // forward a stray `Expect` header through to the backend. nginx
          // (which fronts erp.pranera.in) responds to that with a flat
          // "417 Expectation Failed" instead of actually processing the
          // request — so frappe.auth.logout never runs server-side even
          // though the browser gets back what looks like a real HTTP
          // response. Stripping the header before it's forwarded is the
          // standard fix.
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.removeHeader('expect')
          })
          proxy.on('proxyRes', (proxyRes) => {
            const setCookie = proxyRes.headers['set-cookie']
            if (setCookie) {
              proxyRes.headers['set-cookie'] = setCookie.map(c =>
                c.replace(/;\s*Secure/gi, '').replace(/;\s*SameSite=None/gi, '; SameSite=Lax')
              )
            }
          })
        }
      },
      '/assets': {
        target: BACKEND,
        changeOrigin: true,
        secure: false
      },
      '/files': {
        target: BACKEND,
        changeOrigin: true,
        secure: false
      }
    } : undefined
  },

  build: {
    outDir: path.resolve(__dirname, '../pranera_roll/public/roll_app'),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, 'index.html'),
      output: {
        // Hashed entry + CSS: www/roll_app.py copies these exact tags from the
        // built index.html, so the page and the lazy chunks import the same
        // URL (one app instance) and every deploy gets fresh filenames.
        entryFileNames: 'index-[hash].js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      }
    }
  },

  plugins: [
    vue(),
    VitePWA({
      base: '/assets/pranera_roll/roll_app/',
      registerType: 'autoUpdate',
      workbox: {
        skipWaiting: true,
        clientsClaim: true,
        globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
        // Serve the cached SPA shell for in-app navigations when offline,
        // so reloading /roll-app/rolls works with no network. Exclude /api and
        // /files so those still hit the network (and their own caches below).
        navigateFallback: '/assets/pranera_roll/roll_app/index.html',
        // Create Rolls / Rolls are bundled eagerly and may fall back to the
        // cached shell. My Pick Orders, Pick Order Execution and Verify Rolls are online-only:
        // they POST on every action, and only the server-rendered /roll-app
        // page (www/roll_app.py) injects window.csrf_token — the cached static
        // index.html never has it, so serving them from cache would silently
        // break every POST.
        navigateFallbackDenylist: [
          /^\/api/, /^\/files/, /^\/app/,
          /^\/roll-app\/my-pick-orders/,
          /^\/roll-app\/roll-wise-pick-order-execution/,
          /^\/roll-app\/verify-rolls/,
        ],
        runtimeCaching: [
          {
            // Cache read-only GET list/report data so it's available offline.
            urlPattern: ({ url, request }) =>
              request.method === 'GET' && url.pathname.startsWith('/api/'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'roll-api-get',
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 200, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      manifest: {
        name: 'Pranera Roll App',
        short_name: 'RollApp',
        theme_color: '#1e3a5f',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/roll-app',
        scope: '/roll-app',
        icons: [
          { src: '/assets/pranera_roll/roll_app/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/assets/pranera_roll/roll_app/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/assets/pranera_roll/roll_app/icons/icon-192-maskable.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/assets/pranera_roll/roll_app/icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
        ]
      }
    })
  ]
}))
