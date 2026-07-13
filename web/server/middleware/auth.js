"use strict";
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
exports.__esModule = true;
/**
 * Nitro server middleware — Supabase auth gate for all /api/ routes.
 *
 * Extracts the access token from:
 *   1. `sb-access-token` cookie (explicit)
 *   2. `Authorization: Bearer <token>` header
 *   3. Nuxt Supabase module cookie (`sb-<ref>-auth-token` JSON with .access_token)
 *
 * Validates via supabase.auth.getUser(token) using the service role client,
 * then checks the user's email against the OPS_EMAILS allowlist.
 *
 * Sets event.context.user = { id, email } on success.
 */
var supabase_js_1 = require("@supabase/supabase-js");
var h3_1 = require("h3");
var ACCESS_COOKIE = 'sb-access-token';
var DEFAULT_OPS_EMAILS = 'kalepasch@gmail.com,kale@smrter.us';
function getAllowedEmails() {
    var raw = process.env.OPS_EMAILS || DEFAULT_OPS_EMAILS;
    return new Set(raw
        .split(',')
        .map(function (e) { return e.trim().toLowerCase(); })
        .filter(Boolean));
}
function getAccessToken(event) {
    // 1. Explicit sb-access-token cookie
    var cookie = (0, h3_1.getCookie)(event, ACCESS_COOKIE);
    if (cookie)
        return cookie;
    // 2. Authorization: Bearer header
    var auth = (0, h3_1.getHeader)(event, 'authorization');
    if (auth === null || auth === void 0 ? void 0 : auth.startsWith('Bearer '))
        return auth.slice(7);
    // 3. Nuxt Supabase module cookie: sb-<project-ref>-auth-token (JSON with .access_token)
    var cookies = (0, h3_1.parseCookies)(event);
    for (var _i = 0, _a = Object.entries(cookies); _i < _a.length; _i++) {
        var _b = _a[_i], name_1 = _b[0], value = _b[1];
        if (/^sb-[a-z0-9]+-auth-token$/.test(name_1) && value) {
            try {
                var parsed = JSON.parse(value);
                if (parsed === null || parsed === void 0 ? void 0 : parsed.access_token)
                    return parsed.access_token;
            }
            catch (_c) {
                // Not valid JSON — skip
            }
        }
    }
    return null;
}
exports["default"] = (0, h3_1.defineEventHandler)(function (event) { return __awaiter(void 0, void 0, void 0, function () {
    var path, token, supabaseUrl, serviceKey, supabase, _a, data, error, email, allowed;
    var _b;
    return __generator(this, function (_c) {
        switch (_c.label) {
            case 0:
                path = event.path || event.node.req.url || '';
                // Only protect /api/ routes
                if (!path.startsWith('/api/'))
                    return [2 /*return*/];
                token = getAccessToken(event);
                if (!token) {
                    throw (0, h3_1.createError)({
                        statusCode: 401,
                        statusMessage: 'Unauthorized',
                        message: 'Missing access token'
                    });
                }
                supabaseUrl = process.env.SUPABASE_URL;
                serviceKey = process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
                if (!supabaseUrl || !serviceKey) {
                    throw (0, h3_1.createError)({
                        statusCode: 500,
                        statusMessage: 'Internal Server Error',
                        message: 'Supabase configuration missing'
                    });
                }
                supabase = (0, supabase_js_1.createClient)(supabaseUrl, serviceKey);
                return [4 /*yield*/, supabase.auth.getUser(token)];
            case 1:
                _a = _c.sent(), data = _a.data, error = _a.error;
                if (error || !(data === null || data === void 0 ? void 0 : data.user)) {
                    throw (0, h3_1.createError)({
                        statusCode: 401,
                        statusMessage: 'Unauthorized',
                        message: 'Invalid or expired token'
                    });
                }
                email = (_b = data.user.email) === null || _b === void 0 ? void 0 : _b.toLowerCase();
                if (!email) {
                    throw (0, h3_1.createError)({
                        statusCode: 403,
                        statusMessage: 'Forbidden',
                        message: 'No email associated with account'
                    });
                }
                allowed = getAllowedEmails();
                if (!allowed.has(email)) {
                    throw (0, h3_1.createError)({
                        statusCode: 403,
                        statusMessage: 'Forbidden',
                        message: 'Email not in ops allowlist'
                    });
                }
                event.context.user = { id: data.user.id, email: email };
                return [2 /*return*/];
        }
    });
}); });
