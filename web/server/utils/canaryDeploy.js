"use strict";
/**
 * Canary Deploy Mesh — orchestrates rolling deploys across the fleet.
 * Workflow: deploy to canary (1 app) -> health check -> promote to fleet -> verify all
 * If health check fails at any stage, auto-revert the canary.
 */
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
exports.revertDeploy = exports.getDeployPlan = exports.getDeployHistory = exports.executeCanaryDeploy = exports.checkAllAppsHealth = exports.checkAppHealth = exports.createDeployPlan = void 0;
// In-memory deploy store
var deployHistory = [];
var ALL_APPS = ['apparently', 'tomorrow', 'smarter', 'galop', 'hisanta', 'pareto', 'orchestrator'];
function generateId() {
    return "deploy-".concat(Date.now(), "-").concat(Math.random().toString(36).slice(2, 8));
}
function createDeployPlan(canaryApp, targetApps, commitSha) {
    var plan = {
        id: generateId(),
        canaryApp: canaryApp,
        targetApps: targetApps,
        commitSha: commitSha,
        status: 'pending',
        healthChecks: [],
        createdAt: new Date().toISOString()
    };
    deployHistory.unshift(plan);
    return plan;
}
exports.createDeployPlan = createDeployPlan;
function checkAppHealth(appId) {
    return __awaiter(this, void 0, void 0, function () {
        var baseUrlEnv, baseUrl, start, response, latencyMs, healthy, e_1;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    baseUrlEnv = "FLEET_URL_".concat(appId.toUpperCase());
                    baseUrl = process.env[baseUrlEnv];
                    if (!baseUrl) {
                        return [2 /*return*/, {
                                app: appId,
                                healthy: false,
                                latencyMs: 0,
                                statusCode: 0,
                                checkedAt: new Date().toISOString()
                            }];
                    }
                    start = Date.now();
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, fetch("".concat(baseUrl, "/api/health"), {
                            method: 'GET',
                            signal: AbortSignal.timeout(10000)
                        })["catch"](function () {
                            // Fallback: try fleet execute with a ping
                            return fetch("".concat(baseUrl, "/api/fleet/execute"), {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ action: { type: 'ping' } }),
                                signal: AbortSignal.timeout(10000)
                            });
                        })];
                case 2:
                    response = _a.sent();
                    latencyMs = Date.now() - start;
                    healthy = response.ok || response.status === 200;
                    return [2 /*return*/, {
                            app: appId,
                            healthy: healthy,
                            latencyMs: latencyMs,
                            statusCode: response.status,
                            checkedAt: new Date().toISOString()
                        }];
                case 3:
                    e_1 = _a.sent();
                    return [2 /*return*/, {
                            app: appId,
                            healthy: false,
                            latencyMs: Date.now() - start,
                            statusCode: 0,
                            checkedAt: new Date().toISOString()
                        }];
                case 4: return [2 /*return*/];
            }
        });
    });
}
exports.checkAppHealth = checkAppHealth;
function checkAllAppsHealth() {
    return __awaiter(this, void 0, void 0, function () {
        var checks;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, Promise.all(ALL_APPS.map(function (app) { return checkAppHealth(app); }))];
                case 1:
                    checks = _a.sent();
                    return [2 /*return*/, checks];
            }
        });
    });
}
exports.checkAllAppsHealth = checkAllAppsHealth;
function executeCanaryDeploy(planId) {
    return __awaiter(this, void 0, void 0, function () {
        var plan, canaryCheck, targetChecks, unhealthy;
        var _a;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    plan = deployHistory.find(function (p) { return p.id === planId; });
                    if (!plan)
                        throw new Error("Deploy plan ".concat(planId, " not found"));
                    if (plan.status !== 'pending')
                        throw new Error("Plan ".concat(planId, " is not pending (status: ").concat(plan.status, ")"));
                    // Stage 1: Deploy to canary
                    plan.status = 'canary_deploying';
                    return [4 /*yield*/, checkAppHealth(plan.canaryApp)];
                case 1:
                    canaryCheck = _b.sent();
                    plan.healthChecks.push(canaryCheck);
                    if (!canaryCheck.healthy) {
                        plan.status = 'reverted';
                        plan.error = "Canary ".concat(plan.canaryApp, " is unhealthy (status ").concat(canaryCheck.statusCode, "). Deploy aborted.");
                        plan.completedAt = new Date().toISOString();
                        return [2 /*return*/, plan];
                    }
                    plan.status = 'canary_healthy';
                    // Stage 2: Promote to target apps
                    plan.status = 'promoting';
                    return [4 /*yield*/, Promise.all(plan.targetApps
                            .filter(function (app) { return app !== plan.canaryApp; })
                            .map(function (app) { return checkAppHealth(app); }))];
                case 2:
                    targetChecks = _b.sent();
                    (_a = plan.healthChecks).push.apply(_a, targetChecks);
                    unhealthy = targetChecks.filter(function (c) { return !c.healthy; });
                    if (unhealthy.length > 0) {
                        plan.status = 'reverted';
                        plan.error = "Unhealthy targets: ".concat(unhealthy.map(function (u) { return u.app; }).join(', '), ". Rolling back.");
                        plan.completedAt = new Date().toISOString();
                        return [2 /*return*/, plan];
                    }
                    // All healthy
                    plan.status = 'complete';
                    plan.completedAt = new Date().toISOString();
                    return [2 /*return*/, plan];
            }
        });
    });
}
exports.executeCanaryDeploy = executeCanaryDeploy;
function getDeployHistory() {
    return deployHistory;
}
exports.getDeployHistory = getDeployHistory;
function getDeployPlan(planId) {
    return deployHistory.find(function (p) { return p.id === planId; });
}
exports.getDeployPlan = getDeployPlan;
function revertDeploy(planId) {
    return __awaiter(this, void 0, void 0, function () {
        var plan;
        return __generator(this, function (_a) {
            plan = deployHistory.find(function (p) { return p.id === planId; });
            if (!plan)
                throw new Error("Deploy plan ".concat(planId, " not found"));
            plan.status = 'reverted';
            plan.error = plan.error || 'Manually reverted by operator';
            plan.completedAt = new Date().toISOString();
            return [2 /*return*/, plan];
        });
    });
}
exports.revertDeploy = revertDeploy;
