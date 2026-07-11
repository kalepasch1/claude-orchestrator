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
// GET /api/fleet/proof/:actionId — regulator-grade, offline-verifiable proof for a single
// admin decision: constitution version + autonomy computation + CADE deliberation + signed
// receipt, plus a self-check. The artifact an auditor/regulator/acquirer can validate with
// no DB and no secret.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
var fleetSupabase_1 = require("../../../utils/fleetSupabase");
exports["default"] = defineEventHandler(function (event) { return __awaiter(void 0, void 0, void 0, function () {
    var actionId, sb, r, action, constitution, verdict, card, proof;
    var _a, _b, _c, _d, _e;
    return __generator(this, function (_f) {
        switch (_f.label) {
            case 0:
                actionId = getRouterParam(event, 'actionId');
                sb = (0, fleetSupabase_1.serviceClient)();
                return [4 /*yield*/, sb.from('fleet_admin_actions').select('*').eq('id', actionId).maybeSingle()];
            case 1:
                r = (_f.sent()).data;
                if (!r)
                    throw createError({ statusCode: 404, message: 'action not found' });
                action = {
                    id: r.id, product: r.product, domain: r.domain, type: r.type, actor: r.actor,
                    eventId: (_a = r.event_id) !== null && _a !== void 0 ? _a : undefined, subjectId: (_b = r.subject_id) !== null && _b !== void 0 ? _b : undefined, amountUsd: (_c = r.amount_usd) !== null && _c !== void 0 ? _c : undefined,
                    confidence: Number(r.confidence), reversibility: r.reversibility, blastRadius: r.blast_radius,
                    intent: r.intent, params: (_d = r.params) !== null && _d !== void 0 ? _d : {}, ifNotDone: (_e = r.if_not_done) !== null && _e !== void 0 ? _e : undefined, at: r.created_at
                };
                constitution = (0, fleetAdmin_1.fleetAdminConstitution)();
                verdict = (0, fleetAdmin_1.governFleetAction)({ action: action, constitution: constitution });
                card = (0, fleetAdmin_1.buildApprovalCard)({ action: action, verdict: verdict, callbackUrl: '' });
                proof = (0, fleetAdmin_1.buildDecisionProof)({ action: action, verdict: verdict, constitutionVersion: constitution.version, deliberation: card.deliberation });
                return [2 /*return*/, { proof: proof, verification: (0, fleetAdmin_1.verifyDecisionProof)(proof) }];
        }
    });
}); });
