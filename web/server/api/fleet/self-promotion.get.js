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
// GET /api/fleet/self-promotion — the closed-loop batch: every earned promotion assembled
// into an evidence-backed dossier, filtered to the replay-safe + low-blast set, as ONE
// accept-all card. This is what moves the autonomy rate on its own.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
var fleetSupabase_1 = require("../../utils/fleetSupabase");
var fleetReads_1 = require("../../utils/fleetReads");
exports.default = defineEventHandler(function () { return __awaiter(void 0, void 0, void 0, function () {
    var sb, _a, entries, history, exposureByKey, _i, entries_1, e, _b, _c, _d, batch;
    return __generator(this, function (_e) {
        switch (_e.label) {
            case 0:
                sb = (0, fleetSupabase_1.serviceClient)();
                return [4 /*yield*/, Promise.all([(0, fleetReads_1.ledgerEntries)(sb), (0, fleetReads_1.resolvedHistory)(sb)])];
            case 1:
                _a = _e.sent(), entries = _a[0], history = _a[1];
                exposureByKey = new Map();
                _i = 0, entries_1 = entries;
                _e.label = 2;
            case 2:
                if (!(_i < entries_1.length)) return [3 /*break*/, 5];
                e = entries_1[_i];
                _c = (_b = exposureByKey).set;
                _d = ["".concat(e.domain, "::").concat(e.actionType)];
                return [4 /*yield*/, (0, fleetReads_1.exposureFor)(sb, e.domain, e.actionType)];
            case 3:
                _c.apply(_b, _d.concat([_e.sent()]));
                _e.label = 4;
            case 4:
                _i++;
                return [3 /*break*/, 2];
            case 5:
                batch = (0, fleetAdmin_1.assembleSelfPromotionBatch)({
                    entries: entries,
                    history: history,
                    exposureFor: function (d, t) { var _a; return (_a = exposureByKey.get("".concat(d, "::").concat(t))) !== null && _a !== void 0 ? _a : []; },
                    ceilingOf: function (d) { return fleetAdmin_1.DEFAULT_DOMAIN_POLICIES[d].ceiling; },
                });
                return [2 /*return*/, batch];
        }
    });
}); });
