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
exports.SEED_POLICIES = exports.suggestPolicies = exports.recordPolicyMatch = exports.findMatchingPolicies = exports.evaluateConditions = void 0;
/**
 * Policy Engine — natural-language policy definitions that auto-resolve common admin actions.
 *
 * Policies are stored in the fleet_policies table and evaluated against incoming events.
 * When an event matches a policy's conditions, the policy's actions are auto-executed
 * (subject to domain autonomy ceilings from fleetAdmin).
 *
 * Self-improving: the approverProfile learning system feeds back into policy suggestions.
 */
var fleetSupabase_1 = require("./fleetSupabase");
// ── Core evaluation ──────────────────────────────────────────────────────
function evaluateConditions(conditions, event) {
    return conditions.every(function (c) {
        var val = getNestedValue(event, c.field);
        switch (c.op) {
            case 'eq': return val === c.value;
            case 'neq': return val !== c.value;
            case 'gt': return typeof val === 'number' && val > c.value;
            case 'lt': return typeof val === 'number' && val < c.value;
            case 'gte': return typeof val === 'number' && val >= c.value;
            case 'lte': return typeof val === 'number' && val <= c.value;
            case 'contains': return typeof val === 'string' && val.includes(c.value);
            case 'exists': return val !== undefined && val !== null;
            default: return false;
        }
    });
}
exports.evaluateConditions = evaluateConditions;
function getNestedValue(obj, path) {
    return path.split('.').reduce(function (o, k) { return o === null || o === void 0 ? void 0 : o[k]; }, obj);
}
function findMatchingPolicies(event) {
    return __awaiter(this, void 0, void 0, function () {
        var sb, data;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    return [4 /*yield*/, sb
                            .from('fleet_policies')
                            .select('*')
                            .eq('enabled', true)
                            .or("product.eq.".concat(event.product, ",product.eq.*"))
                            .eq('domain', domainFromCategory(event.category))];
                case 1:
                    data = (_a.sent()).data;
                    if (!data)
                        return [2 /*return*/, []];
                    return [2 /*return*/, data.filter(function (p) {
                            var policy = p;
                            // Check trigger
                            if (policy.trigger.eventCategory !== event.category)
                                return false;
                            if (policy.trigger.severity && policy.trigger.severity !== event.severity)
                                return false;
                            // Check conditions
                            return evaluateConditions(policy.conditions, event);
                        })];
            }
        });
    });
}
exports.findMatchingPolicies = findMatchingPolicies;
function recordPolicyMatch(policyId, success) {
    return __awaiter(this, void 0, void 0, function () {
        var sb, now;
        var _this = this;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    now = new Date().toISOString();
                    // Increment match count atomically
                    return [4 /*yield*/, sb.rpc('increment_policy_match', { policy_id: policyId, was_success: success })
                            .then(function () { })["catch"](function () { return __awaiter(_this, void 0, void 0, function () {
                            var data;
                            return __generator(this, function (_a) {
                                switch (_a.label) {
                                    case 0: return [4 /*yield*/, sb.from('fleet_policies').select('match_count, success_count').eq('id', policyId).single()];
                                    case 1:
                                        data = (_a.sent()).data;
                                        if (!data) return [3 /*break*/, 3];
                                        return [4 /*yield*/, sb.from('fleet_policies').update({
                                                match_count: (data.match_count || 0) + 1,
                                                success_count: (data.success_count || 0) + (success ? 1 : 0),
                                                last_matched_at: now
                                            }).eq('id', policyId)];
                                    case 2:
                                        _a.sent();
                                        _a.label = 3;
                                    case 3: return [2 /*return*/];
                                }
                            });
                        }); })];
                case 1:
                    // Increment match count atomically
                    _a.sent();
                    return [2 /*return*/];
            }
        });
    });
}
exports.recordPolicyMatch = recordPolicyMatch;
function suggestPolicies() {
    return __awaiter(this, void 0, void 0, function () {
        var sb, ledger;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    sb = (0, fleetSupabase_1.serviceClient)();
                    return [4 /*yield*/, sb
                            .from('fleet_autonomy_ledger')
                            .select('*')
                            .gte('streak', 5) // 5+ consecutive clean approvals
                            .gte('clean_approvals', 10) // minimum sample size
                            .order('streak', { ascending: false })];
                case 1:
                    ledger = (_a.sent()).data;
                    if (!(ledger === null || ledger === void 0 ? void 0 : ledger.length))
                        return [2 /*return*/, []];
                    return [2 /*return*/, ledger.map(function (entry) { return ({
                            name: "Auto-".concat(entry.action_type, " for ").concat(entry.domain),
                            description: "".concat(entry.clean_approvals, " consecutive clean approvals \u2014 promote to auto-execute"),
                            product: '*',
                            domain: entry.domain,
                            trigger: { eventCategory: entry.action_type },
                            conditions: [],
                            actions: [{ type: entry.action_type, params: {} }],
                            confidence: entry.clean_approvals / (entry.total || 1),
                            basedOn: entry.total
                        }); })];
            }
        });
    });
}
exports.suggestPolicies = suggestPolicies;
// ── Helpers ──────────────────────────────────────────────────────────────
function domainFromCategory(category) {
    var map = {
        compliance: 'trust_safety', security: 'trust_safety', fraud: 'trust_safety',
        billing: 'billing', subscription: 'billing', refund: 'billing',
        user: 'users_access', access: 'users_access', auth: 'users_access',
        infra: 'infra', deploy: 'infra', monitoring: 'infra',
        redemption: 'billing', submission: 'trust_safety', trade: 'trust_safety'
    };
    return map[category] || 'infra';
}
// ── Default seed policies ────────────────────────────────────────────────
exports.SEED_POLICIES = [
    {
        name: 'Auto-approve small HiSanta redemptions',
        description: 'Redemptions under 100 sparks are auto-approved if child has clean history',
        product: 'hisanta',
        domain: 'billing',
        trigger: { eventCategory: 'redemption' },
        conditions: [
            { field: 'details.sparks', op: 'lte', value: 100 },
            { field: 'details.childFlagged', op: 'eq', value: false },
        ],
        actions: [{ type: 'approve_redemption', params: {} }],
        enabled: true,
        autoExecute: true
    },
    {
        name: 'Auto-approve Apparently submissions under review threshold',
        description: 'Standard submissions with confidence > 0.9 skip manual review',
        product: 'apparently',
        domain: 'trust_safety',
        trigger: { eventCategory: 'submission' },
        conditions: [
            { field: 'details.confidence', op: 'gte', value: 0.9 },
            { field: 'details.jurisdiction', op: 'neq', value: 'restricted' },
        ],
        actions: [{ type: 'approve_submission', params: {} }],
        enabled: true,
        autoExecute: true
    },
    {
        name: 'Flag high-value Galop bets',
        description: 'Bets over $500 from new players get flagged for review',
        product: 'galop',
        domain: 'trust_safety',
        trigger: { eventCategory: 'bet', severity: 'warn' },
        conditions: [
            { field: 'amountUsd', op: 'gt', value: 500 },
            { field: 'details.playerAge', op: 'lt', value: 30 }, // days since signup
        ],
        actions: [{ type: 'flag_bet', params: { reason: 'high-value bet from new player' } }],
        enabled: true,
        autoExecute: false
    },
    {
        name: 'Auto-retry failed Tomorrow settlements',
        description: 'Settlement failures from transient errors get one automatic retry',
        product: 'tomorrow',
        domain: 'billing',
        trigger: { eventCategory: 'settlement', severity: 'warn' },
        conditions: [
            { field: 'details.errorType', op: 'eq', value: 'transient' },
            { field: 'details.retryCount', op: 'lt', value: 1 },
        ],
        actions: [{ type: 'retry_settlement', params: {} }],
        enabled: true,
        autoExecute: true
    },
    {
        name: 'Never auto-execute Pareto money movements',
        description: 'All fund transfers in Pareto require human approval — no exceptions',
        product: 'pareto',
        domain: 'billing',
        trigger: { eventCategory: 'transfer' },
        conditions: [],
        actions: [],
        enabled: true,
        autoExecute: false
    },
];
