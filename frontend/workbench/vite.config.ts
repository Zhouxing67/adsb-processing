import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
  build: {
    target: 'es2022',
    outDir: '../../src/airport_workbench/web_dist',
    emptyOutDir: true,
  },
});
