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
exports.supabasePorts = exports.appBaseUrl = exports.serviceClient = void 0;
/**
 * Supabase + HTTP wiring for the Fleet Admin Control Plane ports. Uses the SERVICE
 * ROLE key (the plane is trusted infra; RLS is enforced for the dashboard + bridge).
 */
var supabase_js_1 = require("@supabase/supabase-js");
function serviceClient() {
    return (0, supabase_js_1.createClient)(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY);
}
exports.serviceClient = serviceClient;
/** Per-product base URL for execute delegation + deep links (env: FLEET_URL_APPARENTLY, ...). */
function appBaseUrl(product) {
    var _a;
    return (_a = process.env["FLEET_URL_".concat(product.toUpperCase())]) !== null && _a !== void 0 ? _a : null;
}
exports.appBaseUrl = appBaseUrl;
function actionFromRow(r) {
    var _a, _b, _c, _d, _e, _f;
    return {
        id: r.id, product: r.product, domain: r.domain, type: r.type, actor: r.actor,
        eventId: (_a = r.event_id) !== null && _a !== void 0 ? _a : undefined, subjectId: (_b = r.subject_id) !== null && _b !== void 0 ? _b : undefined,
        amountUsd: (_c = r.amount_usd) !== null && _c !== void 0 ? _c : undefined, confidence: Number(r.confidence),
        reversibility: r.reversibility, blastRadius: r.blast_radius, intent: r.intent,
        params: (_d = r.params) !== null && _d !== void 0 ? _d : {}, ifNotDone: (_e = r.if_not_done) !== null && _e !== void 0 ? _e : undefined, at: (_f = r.created_at) !== null && _f !== void 0 ? _f : r.at
    };
}
function cardFromRow(r) {
    var _a, _b, _c, _d;
    return {
        id: r.id, actionId: r.action_id, product: r.product, domain: r.domain, tier: r.tier,
        priority: r.priority, title: r.title, why: r.why, value: r.value, risk: r.risk,
        alternatives: (_a = r.alternatives) !== null && _a !== void 0 ? _a : [], intent: r.intent, ifNotDone: (_b = r.if_not_done) !== null && _b !== void 0 ? _b : undefined,
        amountUsd: (_c = r.amount_usd) !== null && _c !== void 0 ? _c : undefined, sourceUrl: (_d = r.source_url) !== null && _d !== void 0 ? _d : undefined,
        receiptDigest: r.receipt_digest, callbackUrl: r.callback_url, status: r.status, createdAt: r.created_at
    };
}
function supabasePorts(sb) {
    return {
        saveEvent: function (e) {
            var _a;
            return __awaiter(this, void 0, void 0, function () {
                return __generator(this, function (_b) {
                    switch (_b.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_admin_events').upsert({
                                id: e.id, product: e.product, domain: e.domain, category: e.category, raw_category: e.rawCategory,
                                severity: e.severity, title: e.title, summary: e.summary, subject_id: e.subjectId,
                                amount_usd: e.amountUsd, details: (_a = e.details) !== null && _a !== void 0 ? _a : {}, source_url: e.sourceUrl, at: e.at
                            })];
                        case 1:
                            _b.sent();
                            return [2 /*return*/];
                    }
                });
            });
        },
        saveAction: function (a, v) {
            var _a;
            return __awaiter(this, void 0, void 0, function () {
                return __generator(this, function (_b) {
                    switch (_b.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_admin_actions').upsert({
                                id: a.id, event_id: a.eventId, product: a.product, domain: a.domain, type: a.type, actor: a.actor,
                                subject_id: a.subjectId, amount_usd: a.amountUsd, confidence: a.confidence, reversibility: a.reversibility,
                                blast_radius: a.blastRadius, intent: a.intent, params: (_a = a.params) !== null && _a !== void 0 ? _a : {}, if_not_done: a.ifNotDone,
                                decision: v.decision, tier: v.tier, receipt_digest: v.receipt.digest, created_at: a.at
                            })];
                        case 1:
                            _b.sent();
                            return [2 /*return*/];
                    }
                });
            });
        },
        saveReceipt: function (r) {
            var _a, _b, _c;
            return __awaiter(this, void 0, void 0, function () {
                return __generator(this, function (_d) {
                    switch (_d.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_receipts').upsert({
                                id: r.id, chain: r.chain, seq: r.seq, prev_hash: r.prevHash, digest: r.digest,
                                signature: r.signature, action_id: (_c = (_b = (_a = r.action) === null || _a === void 0 ? void 0 : _a.metadata) === null || _b === void 0 ? void 0 : _b.eventId) !== null && _c !== void 0 ? _c : null,
                                decision: r.decision, reason: r.reason, at: r.at
                            })];
                        case 1:
                            _d.sent();
                            return [2 /*return*/];
                    }
                });
            });
        },
        prevReceipt: function (chain) {
            return __awaiter(this, void 0, void 0, function () {
                var data;
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_receipts').select('*').eq('chain', chain).order('seq', { ascending: false }).limit(1).maybeSingle()];
                        case 1:
                            data = (_a.sent()).data;
                            if (!data)
                                return [2 /*return*/, null];
                            return [2 /*return*/, {
                                    id: data.id, chain: data.chain, seq: data.seq, prevHash: data.prev_hash, action: {},
                                    decision: data.decision, ruleId: null, reason: data.reason, at: data.at, digest: data.digest, signature: data.signature
                                }];
                    }
                });
            });
        },
        saveApproval: function (c) {
            return __awaiter(this, void 0, void 0, function () {
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_approvals').upsert({
                                id: c.id, action_id: c.actionId, product: c.product, domain: c.domain, tier: c.tier, priority: c.priority,
                                title: c.title, why: c.why, value: c.value, risk: c.risk, alternatives: c.alternatives, intent: c.intent,
                                if_not_done: c.ifNotDone, amount_usd: c.amountUsd, source_url: c.sourceUrl, receipt_digest: c.receiptDigest,
                                callback_url: c.callbackUrl, status: c.status, created_at: c.createdAt
                            })];
                        case 1:
                            _a.sent();
                            return [2 /*return*/];
                    }
                });
            });
        },
        markApprovalMirrored: function (actionId) {
            return __awaiter(this, void 0, void 0, function () {
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_approvals').update({ mirrored_to_smarter: true }).eq('action_id', actionId)];
                        case 1:
                            _a.sent();
                            return [2 /*return*/];
                    }
                });
            });
        },
        getApproval: function (actionId) {
            return __awaiter(this, void 0, void 0, function () {
                var data;
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_approvals').select('*').eq('action_id', actionId).maybeSingle()];
                        case 1:
                            data = (_a.sent()).data;
                            return [2 /*return*/, data ? cardFromRow(data) : null];
                    }
                });
            });
        },
        getAction: function (actionId) {
            return __awaiter(this, void 0, void 0, function () {
                var data;
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_admin_actions').select('*').eq('id', actionId).maybeSingle()];
                        case 1:
                            data = (_a.sent()).data;
                            return [2 /*return*/, data ? actionFromRow(data) : null];
                    }
                });
            });
        },
        updateApprovalStatus: function (actionId, status, approver, note) {
            return __awaiter(this, void 0, void 0, function () {
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_approvals').update({ status: status, approver: approver, note: note, decided_at: new Date().toISOString() }).eq('action_id', actionId)];
                        case 1:
                            _a.sent();
                            return [2 /*return*/];
                    }
                });
            });
        },
        markExecuted: function (actionId, ref, undoToken, error) {
            return __awaiter(this, void 0, void 0, function () {
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_admin_actions').update({
                                executed: !error, execution_ref: ref, undo_token: undoToken, error: error !== null && error !== void 0 ? error : null, executed_at: new Date().toISOString()
                            }).eq('id', actionId)];
                        case 1:
                            _a.sent();
                            return [2 /*return*/];
                    }
                });
            });
        },
        isApprover: function (email) {
            return __awaiter(this, void 0, void 0, function () {
                var data;
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_approvers').select('email').eq('email', email).maybeSingle()];
                        case 1:
                            data = (_a.sent()).data;
                            return [2 /*return*/, !!data];
                    }
                });
            });
        },
        recordLedger: function (domain, actionType, decision) {
            return __awaiter(this, void 0, void 0, function () {
                var data, base;
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb.from('fleet_autonomy_ledger').select('*').eq('domain', domain).eq('action_type', actionType).maybeSingle()];
                        case 1:
                            data = (_a.sent()).data;
                            base = data !== null && data !== void 0 ? data : { domain: domain, action_type: actionType, streak: 0, total: 0, clean_approvals: 0, edits: 0, rejections: 0 };
                            base.total += 1;
                            if (decision === 'approve') {
                                base.streak += 1;
                                base.clean_approvals += 1;
                            }
                            else {
                                base.streak = 0;
                                if (decision === 'modify')
                                    base.edits += 1;
                                else
                                    base.rejections += 1;
                            }
                            base.updated_at = new Date().toISOString();
                            return [4 /*yield*/, sb.from('fleet_autonomy_ledger').upsert(base)];
                        case 2:
                            _a.sent();
                            return [2 /*return*/];
                    }
                });
            });
        },
        pushToSmarter: function (card) {
            var _a;
            return __awaiter(this, void 0, void 0, function () {
                var url, res, _b;
                return __generator(this, function (_c) {
                    switch (_c.label) {
                        case 0:
                            url = process.env.SMARTER_INBOX_URL;
                            if (!url)
                                return [2 /*return*/, false];
                            _c.label = 1;
                        case 1:
                            _c.trys.push([1, 3, , 4]);
                            return [4 /*yield*/, fetch(url, {
                                    method: 'POST',
                                    headers: { 'content-type': 'application/json', 'x-fleet-secret': (_a = process.env.FLEET_SHARED_SECRET) !== null && _a !== void 0 ? _a : '' },
                                    body: JSON.stringify({ card: card })
                                })];
                        case 2:
                            res = _c.sent();
                            return [2 /*return*/, res.ok];
                        case 3:
                            _b = _c.sent();
                            return [2 /*return*/, false];
                        case 4: return [2 /*return*/];
                    }
                });
            });
        },
        recentCases: function (action) {
            return __awaiter(this, void 0, void 0, function () {
                var data, outcomeOf;
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0: return [4 /*yield*/, sb
                                .from('fleet_approvals')
                                .select('status, act:fleet_admin_actions(domain,type,amount_usd,reversibility,blast_radius,created_at)')
                                .neq('status', 'pending')
                                .eq('domain', action.domain)
                                .order('decided_at', { ascending: false })
                                .limit(500)];
                        case 1:
                            data = (_a.sent()).data;
                            outcomeOf = function (s) { return (s === 'approved' ? 'approve' : s === 'modified' ? 'modify' : 'reject'); };
                            return [2 /*return*/, (data !== null && data !== void 0 ? data : [])
                                    .filter(function (r) { return r.act; })
                                    .map(function (r) {
                                    var _a;
                                    return ({
                                        domain: r.act.domain, type: r.act.type, amountUsd: (_a = r.act.amount_usd) !== null && _a !== void 0 ? _a : undefined,
                                        reversibility: r.act.reversibility, blastRadius: r.act.blast_radius,
                                        outcome: outcomeOf(r.status), at: r.act.created_at
                                    });
                                })];
                    }
                });
            });
        },
        delegateExecute: function (action) {
            var _a;
            return __awaiter(this, void 0, void 0, function () {
                var base, res, j, e_1;
                return __generator(this, function (_b) {
                    switch (_b.label) {
                        case 0:
                            base = appBaseUrl(action.product);
                            if (!base)
                                return [2 /*return*/, { ok: false, error: "no_execute_url_for_".concat(action.product) }];
                            _b.label = 1;
                        case 1:
                            _b.trys.push([1, 4, , 5]);
                            return [4 /*yield*/, fetch("".concat(base, "/api/fleet/execute"), {
                                    method: 'POST',
                                    headers: { 'content-type': 'application/json', 'x-fleet-secret': (_a = process.env.FLEET_SHARED_SECRET) !== null && _a !== void 0 ? _a : '' },
                                    body: JSON.stringify({ action: action })
                                })];
                        case 2:
                            res = _b.sent();
                            if (!res.ok)
                                return [2 /*return*/, { ok: false, error: "app_execute_".concat(res.status) }];
                            return [4 /*yield*/, res.json()];
                        case 3:
                            j = _b.sent();
                            return [2 /*return*/, { ok: !!j.ok, ref: j.ref, undoToken: j.undoToken, error: j.error }];
                        case 4:
                            e_1 = _b.sent();
                            return [2 /*return*/, { ok: false, error: String(e_1) }];
                        case 5: return [2 /*return*/];
                    }
                });
            });
        }
    };
}
exports.supabasePorts = supabasePorts;
