import { resolve } from 'node:path';
import { defineConfig } from '@playwright/test';
const python = JSON.stringify(resolve(process.platform === 'win32' ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python'));
const fixture = JSON.stringify(resolve('../../tests/browser_fixture.py'));
export default defineConfig({
  testDir: './tests/browser', workers: 1, timeout: 30000,
  use: { channel: process.platform === 'win32' ? 'msedge' : undefined, headless: true, viewport: { width: 1600, height: 1000 }, trace: 'retain-on-failure' },
  webServer: [
    { command: `${python} ${fixture} --port 8891`, url: 'http://127.0.0.1:8891/api/state', reuseExistingServer: false },
    { command: `${python} ${fixture} --port 8892 --flights 18`, url: 'http://127.0.0.1:8892/api/state', reuseExistingServer: false },
  ],
  projects: [
    { name: 'editing', testMatch: 'editing.spec.ts', use: { baseURL: 'http://127.0.0.1:8891' } },
    { name: 'flights', testMatch: 'flights.spec.ts', use: { baseURL: 'http://127.0.0.1:8892' } },
  ],
});
