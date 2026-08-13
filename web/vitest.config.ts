import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import path from 'path';

export default defineConfig({
  plugins: [vue() as any],
  // Keep tests hermetic across Macs; do not search above the repo for PostCSS config.
  css: { postcss: { plugins: [] } },
  esbuild: {
    // Prevent Vite from resolving web/tsconfig.json which extends
    // .nuxt/tsconfig.json — that file only exists after `nuxt prepare`.
    tsconfigRaw: JSON.stringify({
      compilerOptions: {
        target: 'es2022',
        module: 'esnext',
        moduleResolution: 'bundler',
        strict: true,
        esModuleInterop: true,
        jsx: 'preserve',
        types: ['node'],
      },
    }),
  },
  test: {
    globals: true,
    environment: 'node',
    include: ['server/utils/**/*.test.ts', 'server/utils/**/*.spec.ts', 'server/engines/**/*.test.ts', 'server/engines/**/*.spec.ts', 'composables/**/*.test.ts', 'composables/**/*.spec.ts'],
    exclude: ['node_modules', 'dist', '.idea', '.git', '.cache'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './'),
      // Nuxt resolves `~` at build time; vitest does not. Without this, any test
      // that imports an SFC fails on the component's own `~/utils/...` imports.
      '~': path.resolve(__dirname, './'),
    },
  },
});
