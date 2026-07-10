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
// POST /api/fleet/ingest  { event: AdminEvent, proposedActions: AdminAction[] }
// Apps (or their adapters / domain swarms) push admin events + proposed remediations
// here. The plane governs each, auto-runs the safe ones, and raises approvals for the
// rest (mirroring them into Bear's Smarter inbox).
var fleetPlane_1 = require("../../utils/fleetPlane");
var fleetSupabase_1 = require("../../utils/fleetSupabase");
exports.default = defineEventHandler(function (event) { return __awaiter(void 0, void 0, void 0, function () {
    var secret, body, ports, cfg, verdicts;
    var _a, _b, _c, _d;
    return __generator(this, function (_e) {
        switch (_e.label) {
            case 0:
                secret = (_a = getHeader(event, 'x-fleet-secret')) !== null && _a !== void 0 ? _a : '';
                if (((_b = process.env.FLEET_SHARED_SECRET) !== null && _b !== void 0 ? _b : '') && secret !== process.env.FLEET_SHARED_SECRET) {
                    throw createError({ statusCode: 401, message: 'bad_fleet_secret' });
                }
                return [4 /*yield*/, readBody(event)];
            case 1:
                body = _e.sent();
                if (!(body === null || body === void 0 ? void 0 : body.event))
                    throw createError({ statusCode: 400, message: 'event required' });
                ports = (0, fleetSupabase_1.supabasePorts)((0, fleetSupabase_1.serviceClient)());
                cfg = {
                    callbackUrl: "".concat((_c = process.env.ORCHESTRATOR_BASE_URL) !== null && _c !== void 0 ? _c : '', "/api/fleet/callback"),
                    // Onboard a new app safely: set FLEET_SHADOW_MODE=true to govern + record without executing
                    // or bugging a human, until the agreement rate justifies granting real autonomy.
                    shadowMode: process.env.FLEET_SHADOW_MODE === 'true',
                };
                return [4 /*yield*/, (0, fleetPlane_1.ingestEvent)(ports, cfg, body.event, (_d = body.proposedActions) !== null && _d !== void 0 ? _d : [])];
            case 2:
                verdicts = (_e.sent()).verdicts;
                return [2 /*return*/, {
                        ok: true,
                        routed: verdicts.map(function (v) { return ({ decision: v.decision, tier: v.tier, summary: v.summary }); }),
                    }];
        }
    });
}); });
