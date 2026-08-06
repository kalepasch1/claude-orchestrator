import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import path from 'path';

export default defineConfig({
  // Cast is a duplicate-vite artifact, not a config error. `vite` is not a declared
  // dependency here: the top level resolves vite@6.4.3 transitively via nuxt, while
  // vitest@^1 pins its own nested vite@5.4.21. @vitejs/plugin-vue types against the former
  // and vitest/config against the latter, so two structurally identical Plugin types are
  // nominally incompatible (TS2769).
  //
  // The durable fix is a version alignment — bump vitest to a line built on vite 6, or
  // declare and pin vite so npm dedupes to one copy. That is a breaking dependency decision
  // with its own test-surface risk, so it is deliberately NOT bundled into a typecheck fix.
  plugins: [vue() as any],
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
    include: ['server/utils/**/*.test.ts', 'server/utils/**/*.spec.ts', 'server/engines/**/*.test.ts', 'server/engines/**/*.spec.ts'],
    exclude: ['node_modules', 'dist', '.idea', '.git', '.cache'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './'),
    },
  },
});
