"use strict";
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
Object.defineProperty(exports, "__esModule", { value: true });
var node_url_1 = require("node:url");
var kernel = function (path) {
    return (0, node_url_1.fileURLToPath)(new URL("../packages/darwin-kernel/src/".concat(path), import.meta.url));
};
var kernelAlias = {
    '@darwin/kernel': kernel('index.ts'),
    '@darwin/kernel/fleetAdmin': kernel('fleetAdmin/index.ts'),
    '@darwin/kernel/governance': kernel('governance/index.ts')
};
var appAlias = __assign(__assign({}, kernelAlias), { cookie: (0, node_url_1.fileURLToPath)(new URL('./utils/cookie-compat.ts', import.meta.url)) });
// Nuxt config - hosted control plane (deploys to Vercel out of the box).
exports.default = defineNuxtConfig({
    modules: ['@nuxtjs/supabase', '@nuxtjs/tailwindcss'],
    ssr: true,
    experimental: { appManifest: false },
    alias: appAlias,
    // The kernel ships raw ESM/TS (zero deps) — let Vite transpile it in the bundle.
    build: { transpile: ['@darwin/kernel'] },
    vite: {
        resolve: { alias: appAlias },
        ssr: { noExternal: ['@darwin/kernel'] }
    },
    nitro: { alias: appAlias },
    // SUPABASE_URL + SUPABASE_KEY (anon) come from env vars on Vercel.
    supabase: {
        // we gate auth inside index.vue, so don't force a global redirect
        redirect: false
    },
    css: ['~/assets/main.css'],
    app: {
        head: {
            title: 'Claude Orchestrator',
            meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
            link: [
                { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
                { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
                {
                    rel: 'stylesheet',
                    href: 'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&display=swap'
                }
            ]
        }
    }
});
