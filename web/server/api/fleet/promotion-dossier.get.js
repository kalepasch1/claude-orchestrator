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
// GET /api/fleet/promotion-dossier — for each earned autonomy promotion, the full one-tap
// decision packet: VALUE (approvals/$ saved) + SAFETY (replayed false-positive rate) +
// BLAST (portfolio exposure). Recommends only when valuable AND proven-safe AND low-blast.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
var fleetSupabase_1 = require("../../utils/fleetSupabase");
var fleetReads_1 = require("../../utils/fleetReads");
exports["default"] = defineEventHandler(function () { return __awaiter(void 0, void 0, void 0, function () {
    var sb, _a, entries, history, ceilingOf, dossiers, _i, entries_1, entry, exposure, d;
    return __generator(this, function (_b) {
        switch (_b.label) {
            case 0:
                sb = (0, fleetSupabase_1.serviceClient)();
                return [4 /*yield*/, Promise.all([(0, fleetReads_1.ledgerEntries)(sb), (0, fleetReads_1.resolvedHistory)(sb)])];
            case 1:
                _a = _b.sent(), entries = _a[0], history = _a[1];
                ceilingOf = function (d) { return fleetAdmin_1.DEFAULT_DOMAIN_POLICIES[d].ceiling; };
                dossiers = [];
                _i = 0, entries_1 = entries;
                _b.label = 2;
            case 2:
                if (!(_i < entries_1.length)) return [3 /*break*/, 5];
                entry = entries_1[_i];
                return [4 /*yield*/, (0, fleetReads_1.exposureFor)(sb, entry.domain, entry.actionType)];
            case 3:
                exposure = _b.sent();
                d = (0, fleetAdmin_1.promotionDossier)(entry, history, exposure, ceilingOf);
                if (d)
                    dossiers.push(d);
                _b.label = 4;
            case 4:
                _i++;
                return [3 /*break*/, 2];
            case 5:
                dossiers.sort(function (a, b) { return (a.verdict === b.verdict ? b.value.dollarsAtRiskAvoided - a.value.dollarsAtRiskAvoided : a.verdict === 'recommend' ? -1 : 1); });
                return [2 /*return*/, { dossiers: dossiers, total: dossiers.length, recommended: dossiers.filter(function (d) { return d.verdict === 'recommend'; }).length }];
        }
    });
}); });
