// Beethoven design tokens — single source of truth for the orchestrator dashboard.
// GitHub-dark canvas, monospace for machine content, status scale matching the
// existing {color}-500/20 + {color}-300 pill pattern.
// Project is `"type": "module"`, so this is authored as ESM (export default).
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './components/**/*.{vue,js,ts}',
    './pages/**/*.{vue,js,ts}',
    './layouts/**/*.{vue,js,ts}',
    './app.vue',
  ],
  theme: {
    extend: {
      colors: {
        // ── canvas / surfaces ─────────────────────────────────────────────
        canvas: '#0b0e14',
        surface: '#0f1320',          // ≈ slate-900, panel background
        'surface-raised': '#1a2030', // ≈ slate-800, inset/raised wells
        'border-subtle': '#26304a',  // ≈ slate-800/700 dividers
        // ── chart accents (were hardcoded #58a6ff / #8b98ad) ─────────────
        'chart-line': '#58a6ff',
        'chart-axis': '#8b98ad',
        // ── status scale (running/done/queued/retry/blocked) ─────────────
        // each maps to the dot/accent hue; pill backgrounds use /20 alpha.
        status: {
          running: '#3b82f6', // blue-500
          done: '#22c55e',    // green-500
          queued: '#64748b',  // slate-500
          retry: '#f59e0b',   // amber-500
          blocked: '#ef4444', // red-500
        },
      },
      fontFamily: {
        // sans stays the system stack (prose/headers); mono = machine content.
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Consolas',
          'monospace',
        ],
      },
    },
  },
  plugins: [],
}
