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
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
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
Object.defineProperty(exports, "__esModule", { value: true });
// GET /api/fleet/regret — closes the loop on auto-runs. Derives implicit regret signals
// (a chargeback / error-spike / reopened event landing on a subject AFTER we auto-acted on it)
// and reports the per-type regret rate — the KPI that should trend to zero. These regrets also
// feed precedent + replay as implicit rejections so the same shape auto-runs less next time.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
var fleetSupabase_1 = require("../../utils/fleetSupabase");
var REGRET_CATEGORY = {
    chargeback: 'reversed_charge', error_spike: 'rollback', system_error: 'rollback', abuse_report: 'complaint',
};
exports.default = defineEventHandler(function () { return __awaiter(void 0, void 0, void 0, function () {
    var sb, _a, acts, evs, autos, signals, bySubject, _i, _b, e, _loop_1, _c, _d, a, report, regretCases;
    var _e, _f;
    return __generator(this, function (_g) {
        switch (_g.label) {
            case 0:
                sb = (0, fleetSupabase_1.serviceClient)();
                return [4 /*yield*/, Promise.all([
                        sb.from('fleet_admin_actions').select('id,domain,type,amount_usd,reversibility,blast_radius,subject_id,created_at').eq('tier', 'auto').eq('executed', true).limit(5000),
                        sb.from('fleet_admin_events').select('category,subject_id,at').not('subject_id', 'is', null).limit(5000),
                    ])];
            case 1:
                _a = _g.sent(), acts = _a[0].data, evs = _a[1].data;
                autos = (acts !== null && acts !== void 0 ? acts : []).map(function (r) { var _a; return ({ id: r.id, domain: r.domain, type: r.type, amountUsd: (_a = r.amount_usd) !== null && _a !== void 0 ? _a : undefined, reversibility: r.reversibility, blastRadius: r.blast_radius, at: r.created_at }); });
                signals = [];
                bySubject = new Map();
                for (_i = 0, _b = evs !== null && evs !== void 0 ? evs : []; _i < _b.length; _i++) {
                    e = _b[_i];
                    if (REGRET_CATEGORY[e.category])
                        ((_e = bySubject.get(e.subject_id)) !== null && _e !== void 0 ? _e : bySubject.set(e.subject_id, []).get(e.subject_id)).push(e);
                }
                _loop_1 = function (a) {
                    var later = ((_f = bySubject.get(a.subject_id)) !== null && _f !== void 0 ? _f : []).find(function (e) { return Date.parse(e.at) > Date.parse(a.created_at); });
                    if (later)
                        signals.push({ actionId: a.id, kind: REGRET_CATEGORY[later.category], at: later.at });
                };
                for (_c = 0, _d = (acts !== null && acts !== void 0 ? acts : []); _c < _d.length; _c++) {
                    a = _d[_c];
                    _loop_1(a);
                }
                report = (0, fleetAdmin_1.regretReport)(autos, signals);
                regretCases = (0, fleetAdmin_1.regretToResolvedCases)(autos, signals);
                return [2 /*return*/, { report: report, regretCasesForPrecedent: regretCases.length }];
        }
    });
}); });
