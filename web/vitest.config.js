"use strict";
exports.__esModule = true;
var config_1 = require("vitest/config");
var plugin_vue_1 = require("@vitejs/plugin-vue");
var path_1 = require("path");
exports["default"] = (0, config_1.defineConfig)({
    plugins: [(0, plugin_vue_1["default"])()],
    test: {
        globals: true,
        environment: 'node',
        include: ['server/utils/**/*.test.ts', 'server/utils/**/*.spec.ts'],
        exclude: ['node_modules', 'dist', '.idea', '.git', '.cache']
    },
    resolve: {
        alias: {
            '@': path_1["default"].resolve(__dirname, './')
        }
    }
});
