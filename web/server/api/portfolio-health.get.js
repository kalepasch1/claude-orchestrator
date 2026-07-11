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
// GET /api/portfolio-health — one-glance orchestrator health: deploy + security + growth + spend + runner.
var supabase_js_1 = require("@supabase/supabase-js");
exports["default"] = defineEventHandler(function () { return __awaiter(void 0, void 0, void 0, function () {
    var sb, _a, ph, alerts, hb, ship, lastSeen, runnerSecs;
    var _b, _c, _d, _e, _f;
    return __generator(this, function (_g) {
        switch (_g.label) {
            case 0:
                sb = (0, supabase_js_1.createClient)(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY);
                return [4 /*yield*/, Promise.all([
                        sb.from('portfolio_health').select('*'),
                        sb.from('runner_alerts').select('*').eq('resolved', false).order('created_at', { ascending: false }).limit(5),
                        sb.from('runner_heartbeats').select('last_seen').order('last_seen', { ascending: false }).limit(1),
                        sb.from('ship_metrics').select('*').maybeSingle(),
                    ])];
            case 1:
                _a = _g.sent(), ph = _a[0], alerts = _a[1], hb = _a[2], ship = _a[3];
                lastSeen = ((_c = (_b = hb.data) === null || _b === void 0 ? void 0 : _b[0]) === null || _c === void 0 ? void 0 : _c.last_seen) ? new Date(hb.data[0].last_seen).getTime() : 0;
                runnerSecs = lastSeen ? Math.round((Date.now() - lastSeen) / 1000) : null;
                return [2 /*return*/, {
                        apps: (_d = ph.data) !== null && _d !== void 0 ? _d : [],
                        alerts: (_e = alerts.data) !== null && _e !== void 0 ? _e : [],
                        runner: { seconds_since_heartbeat: runnerSecs, up: runnerSecs != null && runnerSecs < 300 },
                        ship: (_f = ship.data) !== null && _f !== void 0 ? _f : null
                    }];
        }
    });
}); });
