"use strict";
/**
 * Cascade Engine — when an action completes in one app, trigger related actions in other apps.
 *
 * Example: New client signs up in Tomorrow → provision Smarter workspace, create Apparently
 * compliance profile, set up Galop operator account.
 *
 * Cascades are defined declaratively and executed through each app's fleet/execute endpoint.
 */
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
exports.DEFAULT_CASCADES = exports.findMatchingCascades = exports.executeCascade = void 0;
// ── Execute cascade ──────────────────────────────────────────────────────
function executeCascade(rule, sourceAction, executeOnApp) {
    return __awaiter(this, void 0, void 0, function () {
        var results, _i, _a, step, params, action, result;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    results = [];
                    _i = 0, _a = rule.targetSteps;
                    _b.label = 1;
                case 1:
                    if (!(_i < _a.length)) return [3 /*break*/, 4];
                    step = _a[_i];
                    // Check condition
                    if (step.condition && !step.condition(sourceAction)) {
                        return [3 /*break*/, 3];
                    }
                    params = typeof step.action.params === 'function'
                        ? step.action.params(sourceAction)
                        : __assign({}, step.action.params);
                    action = {
                        id: "cascade-".concat(rule.id, "-").concat(Date.now(), "-").concat(Math.random().toString(36).slice(2, 6)),
                        product: step.targetProduct,
                        domain: step.action.domain,
                        type: step.action.type,
                        actor: 'cascade-engine',
                        subjectId: sourceAction.subjectId,
                        params: params,
                        intent: "cascade from ".concat(rule.sourceProduct, ":").concat(rule.sourceAction),
                        at: new Date().toISOString()
                    };
                    return [4 /*yield*/, executeOnApp(step.targetProduct, action)];
                case 2:
                    result = _b.sent();
                    results.push({
                        targetProduct: step.targetProduct,
                        actionType: step.action.type,
                        ok: result.ok,
                        ref: result.ref,
                        error: result.error
                    });
                    if (!result.ok && !step.continueOnError)
                        return [3 /*break*/, 4];
                    _b.label = 3;
                case 3:
                    _i++;
                    return [3 /*break*/, 1];
                case 4: return [2 /*return*/, {
                        ruleId: rule.id,
                        ruleName: rule.name,
                        steps: results,
                        allSucceeded: results.every(function (r) { return r.ok; })
                    }];
            }
        });
    });
}
exports.executeCascade = executeCascade;
// ── Find matching cascades ───────────────────────────────────────────────
function findMatchingCascades(sourceProduct, sourceActionType) {
    return exports.DEFAULT_CASCADES.filter(function (c) { return c.enabled && c.sourceProduct === sourceProduct && c.sourceAction === sourceActionType; });
}
exports.findMatchingCascades = findMatchingCascades;
// ── Default cascade definitions ──────────────────────────────────────────
exports.DEFAULT_CASCADES = [
    {
        id: 'cascade-new-client',
        name: 'New client onboarding',
        description: 'When a new client signs up in Tomorrow, provision across all apps',
        sourceProduct: 'tomorrow',
        sourceAction: 'create_client',
        enabled: true,
        targetSteps: [
            {
                targetProduct: 'smarter',
                action: {
                    domain: 'users_access',
                    type: 'provision_workspace',
                    params: function (src) {
                        var _a, _b;
                        return ({
                            workspaceName: (_a = src.params) === null || _a === void 0 ? void 0 : _a.clientName,
                            ownerEmail: (_b = src.params) === null || _b === void 0 ? void 0 : _b.email,
                            tier: 'standard'
                        });
                    }
                }
            },
            {
                targetProduct: 'apparently',
                action: {
                    domain: 'users_access',
                    type: 'create_compliance_profile',
                    params: function (src) {
                        var _a, _b, _c;
                        return ({
                            entityName: (_a = src.params) === null || _a === void 0 ? void 0 : _a.clientName,
                            email: (_b = src.params) === null || _b === void 0 ? void 0 : _b.email,
                            jurisdiction: ((_c = src.params) === null || _c === void 0 ? void 0 : _c.jurisdiction) || 'US'
                        });
                    }
                },
                continueOnError: true
            },
        ]
    },
    {
        id: 'cascade-suspend-cross-app',
        name: 'Cross-app user suspension',
        description: 'Suspending a user in one app suspends them across all apps',
        sourceProduct: '*',
        sourceAction: 'suspend_user',
        enabled: true,
        targetSteps: [
            {
                targetProduct: 'apparently',
                action: { domain: 'users_access', type: 'suspend_user', params: {} },
                continueOnError: true
            },
            {
                targetProduct: 'tomorrow',
                action: { domain: 'users_access', type: 'suspend_user', params: {} },
                continueOnError: true
            },
            {
                targetProduct: 'smarter',
                action: { domain: 'users_access', type: 'suspend_user', params: {} },
                continueOnError: true
            },
            {
                targetProduct: 'galop',
                action: { domain: 'users_access', type: 'ban_player', params: {} },
                continueOnError: true
            },
            {
                targetProduct: 'hisanta',
                action: { domain: 'users_access', type: 'ban_family', params: {} },
                continueOnError: true
            },
            {
                targetProduct: 'pareto',
                action: { domain: 'users_access', type: 'suspend_user', params: {} },
                continueOnError: true
            },
        ]
    },
    {
        id: 'cascade-critical-alert',
        name: 'Critical alert broadcast',
        description: 'Critical events in any app trigger a review in all related apps',
        sourceProduct: '*',
        sourceAction: 'critical_alert',
        enabled: true,
        targetSteps: [
            {
                targetProduct: 'orchestrator',
                action: {
                    domain: 'infra',
                    type: 'create_incident',
                    params: function (src) { return ({
                        source: src.product,
                        title: src.intent || 'Critical alert cascade',
                        severity: 'critical'
                    }); }
                }
            },
        ]
    },
    {
        id: 'cascade-feature-flag-sync',
        name: 'Feature flag sync',
        description: 'Global feature flags propagate to all apps',
        sourceProduct: 'orchestrator',
        sourceAction: 'toggle_global_feature',
        enabled: true,
        targetSteps: [
            { targetProduct: 'apparently', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
            { targetProduct: 'tomorrow', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
            { targetProduct: 'smarter', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
            { targetProduct: 'galop', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
            { targetProduct: 'hisanta', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
            { targetProduct: 'pareto', action: { domain: 'infra', type: 'toggle_feature', params: {} }, continueOnError: true },
        ]
    },
];
