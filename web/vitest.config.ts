import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import path from 'path';

export default defineConfig({
  plugins: [vue()],
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
    include: ['server/utils/**/*.test.ts', 'server/utils/**/*.spec.ts'],
    exclude: ['node_modules', 'dist', '.idea', '.git', '.cache'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './'),
    },
  },
});
