import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  root: fileURLToPath(new URL('./', import.meta.url)),
  plugins: [react()],
  build: { outDir: '../tavrel/web', emptyOutDir: true },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/v1': {
        target: 'http://127.0.0.1:8787', changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (request, incoming) => {
            // Preserve the browser's same-origin check across the local dev
            // proxy. Other origins must reach the gateway unchanged and fail.
            if (incoming.headers.origin === `http://${incoming.headers.host}`
                && incoming.headers['sec-fetch-site'] === 'same-origin') {
              request.setHeader('origin', 'http://127.0.0.1:8787');
            }
          });
        },
      },
    },
  },
});
