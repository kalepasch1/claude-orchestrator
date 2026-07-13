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
exports.ALL_APP_IDS = exports.listApps = exports.getAppConfig = exports.getAppClient = void 0;
/**
 * Per-app Supabase client registry for the unified admin proxy.
 * Each app's credentials come from env vars: SUPABASE_URL_<APP>, SUPABASE_SERVICE_KEY_<APP>.
 * The proxy never uses RLS — it operates with service-role keys, gated by the orchestrator's
 * own auth middleware (OPS_EMAILS allowlist).
 */
var supabase_js_1 = require("@supabase/supabase-js");
var APP_ENV_MAP = {
    apparently: { urlEnv: 'SUPABASE_URL_APPARENTLY', keyEnv: 'SUPABASE_SERVICE_KEY_APPARENTLY', name: 'Apparently', baseUrlEnv: 'FLEET_URL_APPARENTLY' },
    tomorrow: { urlEnv: 'SUPABASE_URL_TOMORROW', keyEnv: 'SUPABASE_SERVICE_KEY_TOMORROW', name: 'Tomorrow', baseUrlEnv: 'FLEET_URL_TOMORROW' },
    smarter: { urlEnv: 'SUPABASE_URL_SMARTER', keyEnv: 'SUPABASE_SERVICE_KEY_SMARTER', name: 'Smarter', baseUrlEnv: 'FLEET_URL_SMARTER' },
    galop: { urlEnv: 'SUPABASE_URL_GALOP', keyEnv: 'SUPABASE_SERVICE_KEY_GALOP', name: 'Galop', baseUrlEnv: 'FLEET_URL_GALOP' },
    hisanta: { urlEnv: 'SUPABASE_URL_HISANTA', keyEnv: 'SUPABASE_SERVICE_KEY_HISANTA', name: 'HiSanta', baseUrlEnv: 'FLEET_URL_HISANTA' },
    pareto: { urlEnv: 'SUPABASE_URL_PARETO', keyEnv: 'SUPABASE_SERVICE_KEY_PARETO', name: 'Pareto', baseUrlEnv: 'FLEET_URL_PARETO' },
    orchestrator: { urlEnv: 'SUPABASE_URL', keyEnv: 'SUPABASE_SERVICE_KEY', name: 'Orchestrator', baseUrlEnv: 'FLEET_URL_ORCHESTRATOR' }
};
var clients = new Map();
function getAppClient(appId) {
    if (clients.has(appId))
        return clients.get(appId);
    var env = APP_ENV_MAP[appId];
    var url = process.env[env.urlEnv];
    var key = process.env[env.keyEnv] || process.env["".concat(env.keyEnv.replace('SERVICE_KEY', 'SERVICE_ROLE_KEY'))];
    if (!url || !key)
        return null;
    var client = (0, supabase_js_1.createClient)(url, key);
    clients.set(appId, client);
    return client;
}
exports.getAppClient = getAppClient;
function getAppConfig(appId) {
    var _a;
    var env = APP_ENV_MAP[appId];
    return {
        name: env.name,
        baseUrl: (_a = process.env[env.baseUrlEnv]) !== null && _a !== void 0 ? _a : null,
        configured: !!(process.env[env.urlEnv] && (process.env[env.keyEnv] || process.env[env.keyEnv.replace('SERVICE_KEY', 'SERVICE_ROLE_KEY')]))
    };
}
exports.getAppConfig = getAppConfig;
function listApps() {
    return Object.keys(APP_ENV_MAP).map(function (id) { return (__assign({ id: id }, getAppConfig(id))); });
}
exports.listApps = listApps;
exports.ALL_APP_IDS = Object.keys(APP_ENV_MAP);
