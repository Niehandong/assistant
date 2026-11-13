/// <reference types="vitest/config" />
import path from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const target = (envKey: string, port: number): string =>
  process.env[envKey] ?? `http://127.0.0.1:${port}`;

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api/v1/auth': { target: target('IAM_URL', 8301), changeOrigin: true },
      '/api/v1/system': { target: target('IAM_URL', 8301), changeOrigin: true },
      '/api/v1/kb': { target: target('KB_URL', 8302), changeOrigin: true },
      '/api/v1/open-platform': { target: target('OPEN_URL', 8303), changeOrigin: true },
      '/api/v1/open': { target: target('OPEN_URL', 8303), changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
