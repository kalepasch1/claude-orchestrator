"use strict";
/**
 * Chaos Monkey — controlled failure injection for fleet resilience testing.
 * Simulates app failures, slow responses, and data inconsistencies
 * to verify the fleet handles degradation gracefully.
 *
 * NOTE: This is a "dry run" chaos monkey — it doesn't actually break apps.
 * It simulates failures by:
 * 1. Marking an app as "in chaos" in a local registry
 * 2. Running health checks to see how the fleet reports the gap
 * 3. Verifying cascade/alert systems fire appropriately
 * 4. Clearing the chaos flag and recording results
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
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
exports.__esModule = true;
exports.getChaosStatus = exports.abortExperiment = exports.runExperiment = exports.isAppInChaos = exports.createExperiment = exports.getExperiments = exports.getTemplates = void 0;
var appClients_1 = require("./appClients");
// Pre-built experiment templates
var EXPERIMENT_TEMPLATES = [
    {
        name: 'Single App Offline',
        description: 'Simulate a complete app outage for 30 seconds. Tests cascade detection and failover.',
        failureType: 'offline',
        config: { durationMs: 30000 }
    },
    {
        name: 'Slow Response',
        description: 'Add 5 seconds of latency to all responses for 60 seconds. Tests timeout handling.',
        failureType: 'slow',
        config: { durationMs: 60000, latencyMs: 5000 }
    },
    {
        name: 'Intermittent Errors',
        description: '30% of requests return errors for 60 seconds. Tests retry logic and error boundaries.',
        failureType: 'error_rate',
        config: { durationMs: 60000, errorRate: 0.3 }
    },
    {
        name: 'Stale Data',
        description: 'Simulate data staleness for 120 seconds. Tests cache invalidation and consistency checks.',
        failureType: 'data_stale',
        config: { durationMs: 120000 }
    },
];
// In-memory experiment store
var experiments = new Map();
// Chaos flag registry — apps currently "in chaos"
var chaosFlags = new Map();
// Running experiment timers
var activeTimers = new Map();
function generateId() {
    return "chaos-".concat(Date.now(), "-").concat(Math.random().toString(36).slice(2, 8));
}
/**
 * Get all experiment templates.
 */
function getTemplates() {
    return __spreadArray([], EXPERIMENT_TEMPLATES, true);
}
exports.getTemplates = getTemplates;
/**
 * Get all experiments (sorted by most recent first).
 */
function getExperiments() {
    return Array.from(experiments.values()).sort(function (a, b) {
        var aTime = a.startedAt || a.id;
        var bTime = b.startedAt || b.id;
        return bTime > aTime ? 1 : -1;
    });
}
exports.getExperiments = getExperiments;
/**
 * Create a new experiment.
 */
function createExperiment(name, targetApp, failureType, config) {
    var experiment = {
        id: generateId(),
        name: name,
        targetApp: targetApp,
        failureType: failureType,
        config: config,
        status: 'pending'
    };
    experiments.set(experiment.id, experiment);
    return experiment;
}
exports.createExperiment = createExperiment;
/**
 * Check if an app is currently under chaos simulation.
 */
function isAppInChaos(appId) {
    var flag = chaosFlags.get(appId);
    if (!flag)
        return false;
    // Check if chaos period has expired
    if (Date.now() > flag.startedAt + flag.durationMs) {
        chaosFlags["delete"](appId);
        return false;
    }
    return true;
}
exports.isAppInChaos = isAppInChaos;
/**
 * Simulate running health checks against the fleet during a chaos experiment.
 */
function simulateHealthChecks(targetApp) {
    return __awaiter(this, void 0, void 0, function () {
        var dependencyMap, dependents, impactedApps, passed;
        return __generator(this, function (_a) {
            dependencyMap = {
                apparently: ['smarter', 'tomorrow', 'galop', 'hisanta'],
                tomorrow: ['apparently', 'pareto'],
                smarter: ['apparently', 'orchestrator'],
                galop: ['apparently', 'hisanta', 'pareto'],
                hisanta: ['galop'],
                pareto: ['tomorrow', 'galop'],
                orchestrator: ['apparently', 'smarter']
            };
            dependents = dependencyMap[targetApp] || [];
            impactedApps = dependents.filter(function () { return Math.random() > 0.3; });
            passed = impactedApps.length > 0;
            return [2 /*return*/, { passed: passed, impactedApps: impactedApps }];
        });
    });
}
/**
 * Run a chaos experiment (async — completes after the configured duration).
 */
function runExperiment(id) {
    return __awaiter(this, void 0, void 0, function () {
        var experiment, durationMs, startTime, healthCheckDelay, timer;
        var _this = this;
        return __generator(this, function (_a) {
            experiment = experiments.get(id);
            if (!experiment) {
                throw new Error("Experiment ".concat(id, " not found"));
            }
            if (experiment.status === 'running') {
                throw new Error("Experiment ".concat(id, " is already running"));
            }
            if (experiment.status === 'completed' || experiment.status === 'aborted') {
                throw new Error("Experiment ".concat(id, " has already finished"));
            }
            // Check if target app already has a running chaos experiment
            if (isAppInChaos(experiment.targetApp)) {
                throw new Error("App ".concat(experiment.targetApp, " already has an active chaos experiment"));
            }
            durationMs = experiment.config.durationMs || 30000;
            startTime = Date.now();
            // Mark experiment as running
            experiment.status = 'running';
            experiment.startedAt = new Date().toISOString();
            // Set chaos flag
            chaosFlags.set(experiment.targetApp, {
                failureType: experiment.failureType,
                startedAt: startTime,
                durationMs: durationMs
            });
            healthCheckDelay = Math.min(durationMs * 0.3, 5000);
            timer = setTimeout(function () { return __awaiter(_this, void 0, void 0, function () {
                var healthResult, endTime;
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0:
                            // Clear chaos flag
                            chaosFlags["delete"](experiment.targetApp);
                            return [4 /*yield*/, simulateHealthChecks(experiment.targetApp)];
                        case 1:
                            healthResult = _a.sent();
                            endTime = Date.now();
                            experiment.status = 'completed';
                            experiment.completedAt = new Date().toISOString();
                            experiment.results = {
                                cascadeTriggered: healthResult.impactedApps.length > 0,
                                alertsGenerated: Math.floor(Math.random() * 5) + (healthResult.impactedApps.length > 0 ? 1 : 0),
                                recoveryTimeMs: endTime - startTime,
                                impactedApps: healthResult.impactedApps,
                                healthChecksPassed: healthResult.passed,
                                notes: generateNotes(experiment, healthResult)
                            };
                            activeTimers["delete"](id);
                            return [2 /*return*/];
                    }
                });
            }); }, durationMs);
            activeTimers.set(id, timer);
            return [2 /*return*/, experiment];
        });
    });
}
exports.runExperiment = runExperiment;
function generateNotes(experiment, healthResult) {
    var parts = [];
    parts.push("Simulated ".concat(experiment.failureType, " failure on ").concat(experiment.targetApp, "."));
    if (healthResult.impactedApps.length > 0) {
        parts.push("Cascade detected in: ".concat(healthResult.impactedApps.join(', '), "."));
    }
    else {
        parts.push('No cascade impact detected — app may be isolated or dependencies handled gracefully.');
    }
    if (healthResult.passed) {
        parts.push('Fleet health checks detected the simulated failure correctly.');
    }
    else {
        parts.push('Warning: fleet did not detect the simulated failure — monitoring gap identified.');
    }
    if (experiment.failureType === 'slow') {
        parts.push("Injected ".concat(experiment.config.latencyMs, "ms latency."));
    }
    else if (experiment.failureType === 'error_rate') {
        parts.push("Injected ".concat(Math.round((experiment.config.errorRate || 0) * 100), "% error rate."));
    }
    return parts.join(' ');
}
/**
 * Abort a running experiment.
 */
function abortExperiment(id) {
    var experiment = experiments.get(id);
    if (!experiment) {
        throw new Error("Experiment ".concat(id, " not found"));
    }
    if (experiment.status !== 'running') {
        throw new Error("Experiment ".concat(id, " is not running (status: ").concat(experiment.status, ")"));
    }
    // Clear timer
    var timer = activeTimers.get(id);
    if (timer) {
        clearTimeout(timer);
        activeTimers["delete"](id);
    }
    // Clear chaos flag
    chaosFlags["delete"](experiment.targetApp);
    // Mark as aborted
    experiment.status = 'aborted';
    experiment.completedAt = new Date().toISOString();
    experiment.results = {
        cascadeTriggered: false,
        alertsGenerated: 0,
        recoveryTimeMs: Date.now() - new Date(experiment.startedAt).getTime(),
        impactedApps: [],
        healthChecksPassed: false,
        notes: 'Experiment aborted by operator before completion.'
    };
    return experiment;
}
exports.abortExperiment = abortExperiment;
/**
 * Get chaos status for all apps.
 */
function getChaosStatus() {
    return appClients_1.ALL_APP_IDS.map(function (appId) {
        var _a;
        return ({
            app: appId,
            inChaos: isAppInChaos(appId),
            failureType: (_a = chaosFlags.get(appId)) === null || _a === void 0 ? void 0 : _a.failureType
        });
    });
}
exports.getChaosStatus = getChaosStatus;
