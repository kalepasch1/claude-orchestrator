// Beethoven design tokens — single source of truth for the orchestrator dashboard.
// Legora-inspired canvas: warm parchment surface, ink text, editorial serif display
// type, restrained sans body. Project is `"type": "module"`, so this is authored as
// ESM (export default).
import colors from 'tailwindcss/colors'

/** @type {import('tailwindcss').Config} */

// The dashboard's inline utility classes (bg-slate-900, text-blue-300, bg-red-900/60,
// ...) were authored for a NEAR-BLACK canvas: high numbers = dark surfaces, low-to-mid
// numbers = light/readable text. Flipping the canvas to a warm light theme without
// touching every call site means mirroring each Tailwind color scale around its
// midpoint (50↔950, 100↔900, 200↔800, ...) so the *same* class names now resolve to
// light-appropriate values: bg-slate-900 becomes a near-white panel, text-slate-300
// becomes dark ink, bg-red-900/60 + text-red-300 becomes a pale-red chip with a dark
// red label, etc. Solid saturated CTA buttons (bg-blue-600 + text-white) are the one
// pattern this breaks — those are hand-pinned to fixed hex in the templates instead of
// relying on the mirrored scale.
function mirror(scale) {
  return {
    50: scale[950],
    100: scale[900],
    200: scale[800],
    300: scale[700],
    400: scale[600],
    500: scale[500],
    600: scale[400],
    700: scale[300],
    800: scale[200],
    900: scale[100],
    950: scale[50],
  }
}

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
        // ── canvas / surfaces — warm parchment, not cold white ────────────
        canvas: '#f6f3ec',
        surface: '#fdfbf6',          // panel background
        'surface-raised': '#efeade', // inset/raised wells
        'border-subtle': '#e2dccb',  // dividers
        ink: '#20201c',              // primary text / wordmark
        // ── chart accents (were hardcoded #58a6ff / #8b98ad) ─────────────
        'chart-line': '#2f5d50',
        'chart-axis': '#8a8368',
        // ── status scale (running/done/queued/retry/blocked) ─────────────
        // each maps to the dot/accent hue; pill backgrounds use /20 alpha.
        status: {
          running: '#2f5d50', // deep green, was blue-500
          done: '#3f7a54',    // green-600
          queued: '#8a8368',  // warm gray
          retry: '#b5852a',   // amber, deepened for light-bg contrast
          blocked: '#b3432f', // brick red
        },
        // ── mirrored neutral + accent scales (see `mirror` above) ─────────
        slate: mirror(colors.slate),
        blue: mirror(colors.blue),
        green: mirror(colors.green),
        red: mirror(colors.red),
        amber: mirror(colors.amber),
        cyan: mirror(colors.cyan),
        indigo: mirror(colors.indigo),
        emerald: mirror(colors.emerald),
        purple: mirror(colors.purple),
        sky: mirror(colors.sky),
      },
      fontFamily: {
        // sans = editorial body/UI face; serif = display wordmark + hero type;
        // mono = machine content (logs, ids, numerics).
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'sans-serif',
        ],
        serif: [
          'Fraunces',
          'ui-serif',
          'Georgia',
          'serif',
        ],
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
