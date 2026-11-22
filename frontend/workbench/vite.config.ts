import { resolve } from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  build: {
    target: 'es2022',
    outDir: '../../src/airport_workbench/web_dist',
    emptyOutDir: true,
  },
});
