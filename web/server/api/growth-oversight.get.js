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
// GET /api/growth-oversight — Orchestrator oversight of the Growth OS.
// Ties marketing (momentum/budget/spend) to AI token usage per app, so marketing spend can steer
// token/improvement focus. Also returns governance accuracy + counterfactual value + campaigns.
var supabase_js_1 = require("@supabase/supabase-js");
exports["default"] = defineEventHandler(function () { return __awaiter(void 0, void 0, void 0, function () {
    var sb, _a, st, gov, camp, cf, rows, totalMom, spendTokens;
    var _b, _c, _d, _e, _f, _g;
    return __generator(this, function (_h) {
        switch (_h.label) {
            case 0:
                sb = (0, supabase_js_1.createClient)(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY);
                return [4 /*yield*/, Promise.all([
                        sb.from('growth_spend_tokens').select('*'),
                        sb.from('growth_governance_analytics').select('*'),
                        sb.from('growth_campaign').select('app,name,status,segment').order('created_at', { ascending: false }).limit(20),
                        sb.from('resource_events').select('value,created_at').eq('kind', 'growth_counterfactual_value').order('created_at', { ascending: false }).limit(1),
                    ])];
            case 1:
                _a = _h.sent(), st = _a[0], gov = _a[1], camp = _a[2], cf = _a[3];
                rows = (_b = st.data) !== null && _b !== void 0 ? _b : [];
                totalMom = rows.reduce(function (s, r) { return s + Number(r.momentum || 0); }, 0) || 1;
                spendTokens = rows.map(function (r) { return (__assign(__assign({}, r), { focus_weight: Math.round((Number(r.momentum || 0) / totalMom) * 100), 
                    // ratio of AI token cost to marketing spend — flags apps burning tokens without marketing traction
                    token_to_marketing: Number(r.marketing_spend) > 0 ? Number((Number(r.token_cost_30d) / Number(r.marketing_spend)).toFixed(2)) : null })); }).sort(function (a, b) { return b.focus_weight - a.focus_weight; });
                return [2 /*return*/, {
                        spendTokens: spendTokens,
                        governance: (_c = gov.data) !== null && _c !== void 0 ? _c : [],
                        campaigns: (_d = camp.data) !== null && _d !== void 0 ? _d : [],
                        counterfactualValue: (_g = (_f = (_e = cf.data) === null || _e === void 0 ? void 0 : _e[0]) === null || _f === void 0 ? void 0 : _f.value) !== null && _g !== void 0 ? _g : null
                    }];
        }
    });
}); });
