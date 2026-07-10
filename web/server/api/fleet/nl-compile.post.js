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
// POST /api/fleet/nl-compile  { text }
// Natural-language control plane: compile an English policy line into an enforceable rule
// and dry-run it against recent actions so Bear sees the diff BEFORE it applies. Returns
// the compiled rules + the twin diff; applying it (persisting the new constitution) is a
// separate, human-confirmed step.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
var fleetSupabase_1 = require("../../utils/fleetSupabase");
exports.default = defineEventHandler(function (event) { return __awaiter(void 0, void 0, void 0, function () {
    var text, sb, data, history, result;
    return __generator(this, function (_a) {
        switch (_a.label) {
            case 0: return [4 /*yield*/, readBody(event)];
            case 1:
                text = (_a.sent()).text;
                if (!text)
                    throw createError({ statusCode: 400, message: 'text required' });
                sb = (0, fleetSupabase_1.serviceClient)();
                return [4 /*yield*/, sb
                        .from('fleet_admin_actions')
                        .select('id,product,domain,type,actor,subject_id,amount_usd,confidence,reversibility,blast_radius,intent,created_at')
                        .order('created_at', { ascending: false })
                        .limit(1000)];
            case 2:
                data = (_a.sent()).data;
                history = (data !== null && data !== void 0 ? data : []).map(function (r) {
                    var _a, _b;
                    return ({
                        id: r.id, product: r.product, domain: r.domain, type: r.type, actor: r.actor,
                        subjectId: (_a = r.subject_id) !== null && _a !== void 0 ? _a : undefined, amountUsd: (_b = r.amount_usd) !== null && _b !== void 0 ? _b : undefined, confidence: Number(r.confidence),
                        reversibility: r.reversibility, blastRadius: r.blast_radius, intent: r.intent, at: r.created_at,
                    });
                });
                result = (0, fleetAdmin_1.compileNlControl)({ text: text, history: history });
                return [2 /*return*/, {
                        normalizedLines: result.normalizedLines,
                        addedRuleCount: result.addedRuleCount,
                        addedRules: result.constitution.rules.slice(-result.addedRuleCount).map(function (r) { return ({ id: r.id, text: r.text, effect: r.effect, appliesTo: r.appliesTo }); }),
                        unmapped: result.unmapped,
                        rejected: result.rejected,
                        dryRun: result.dryRun,
                    }];
        }
    });
}); });
