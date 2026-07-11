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
exports.__esModule = true;
var node_fs_1 = require("node:fs");
var node_path_1 = require("node:path");
function readJson(path, fallback) {
    try {
        if (!(0, node_fs_1.existsSync)(path))
            return fallback;
        return JSON.parse((0, node_fs_1.readFileSync)(path, 'utf8'));
    }
    catch (e) {
        return __assign(__assign({}, fallback), { error: (e === null || e === void 0 ? void 0 : e.message) || String(e) });
    }
}
function lineCount(path) {
    try {
        if (!(0, node_fs_1.existsSync)(path))
            return 0;
        var text = (0, node_fs_1.readFileSync)(path, 'utf8');
        return text ? text.trim().split(/\n+/).filter(Boolean).length : 0;
    }
    catch (_a) {
        return 0;
    }
}
exports["default"] = defineEventHandler(function () {
    var cwd = process.cwd();
    var repoRoot = cwd.endsWith('/web') ? (0, node_path_1.dirname)(cwd) : cwd;
    var runtime = (0, node_path_1.resolve)(repoRoot, '.runtime');
    var mesh = readJson((0, node_path_1.resolve)(runtime, 'resilience_mesh.json'), null);
    var db = readJson((0, node_path_1.resolve)(runtime, 'db_health.json'), null);
    var spoolPath = (0, node_path_1.resolve)(runtime, 'offline_spool', 'resilience_actions.jsonl');
    return {
        updatedAt: new Date().toISOString(),
        mesh: mesh,
        db: db,
        spoolDepth: lineCount(spoolPath)
    };
});
