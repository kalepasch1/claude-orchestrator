"use strict";
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
exports.processAnomalyAlert = exports.createPlaybook = exports.updatePlaybook = exports.getExecutionHistory = exports.getPlaybooks = exports.abortExecution = exports.approveExecution = exports.executePlaybook = exports.matchPlaybook = void 0;
// In-memory state
var playbooks = [];
var executions = [];
var initialized = false;
function ensureDefaults() {
    if (initialized)
        return;
    initialized = true;
    playbooks = [
        {
            id: 'pb-error-spike',
            name: 'Error Spike Response',
            description: 'When error rate spikes, toggle the last-deployed feature flag off and notify',
            trigger: { metricPattern: 'error_rate', severityMin: 'critical' },
            steps: [
                { type: 'toggle_feature', description: 'Disable last deployed feature flag' },
                { type: 'notify', description: 'Alert ops channel' },
            ],
            requiresApproval: false,
            cooldownMs: 300000,
            enabled: true,
            executionCount: 0
        },
        {
            id: 'pb-high-rejection',
            name: 'High Rejection Rate',
            description: 'When approval rejection rate is anomalously high, pause auto-execution and escalate',
            trigger: { metricPattern: 'rejection_rate', severityMin: 'warning' },
            steps: [
                { type: 'custom', action: 'pause_auto_execute', description: 'Pause all auto-execute policies' },
                { type: 'notify', description: 'Escalate to senior ops' },
            ],
            requiresApproval: true,
            cooldownMs: 900000,
            enabled: true,
            executionCount: 0
        },
        {
            id: 'pb-app-down',
            name: 'App Health Failure',
            description: 'When an app fails health checks, check deploy history and offer revert',
            trigger: { metricPattern: 'health_check', severityMin: 'critical' },
            steps: [
                { type: 'revert_deploy', description: 'Revert to last known good deploy' },
                { type: 'notify', description: 'Alert ops with incident details' },
            ],
            requiresApproval: true,
            cooldownMs: 600000,
            enabled: true,
            executionCount: 0
        },
        {
            id: 'pb-volume-drop',
            name: 'Traffic Volume Drop',
            description: 'When event volume drops significantly, run health checks and create incident',
            trigger: { metricPattern: 'event_volume', severityMin: 'warning' },
            steps: [
                { type: 'custom', action: 'health_check_all', description: 'Run health checks on all apps' },
                { type: 'notify', description: 'Create incident report' },
            ],
            requiresApproval: false,
            cooldownMs: 600000,
            enabled: true,
            executionCount: 0
        },
    ];
}
function makeExecutionId() {
    return "exec-".concat(Date.now(), "-").concat(Math.random().toString(36).slice(2, 8));
}
/**
 * Find the first enabled playbook whose trigger matches the given anomaly alert.
 */
function matchPlaybook(alert) {
    ensureDefaults();
    var severityRank = { info: 0, warning: 1, critical: 2 };
    for (var _i = 0, playbooks_1 = playbooks; _i < playbooks_1.length; _i++) {
        var pb = playbooks_1[_i];
        if (!pb.enabled)
            continue;
        // Check metric pattern
        try {
            var metricRegex = new RegExp(pb.trigger.metricPattern, 'i');
            var metricStr = alert.metric.toLowerCase().replace(/\s+/g, '_');
            if (!metricRegex.test(metricStr))
                continue;
        }
        catch (_a) {
            continue;
        }
        // Check severity minimum
        if (severityRank[alert.severity] < severityRank[pb.trigger.severityMin])
            continue;
        // Check app pattern
        if (pb.trigger.appPattern && pb.trigger.appPattern !== '*') {
            try {
                var appRegex = new RegExp(pb.trigger.appPattern, 'i');
                if (!appRegex.test(alert.app))
                    continue;
            }
            catch (_b) {
                continue;
            }
        }
        // Check cooldown
        if (pb.lastExecutedAt) {
            var elapsed = Date.now() - new Date(pb.lastExecutedAt).getTime();
            if (elapsed < pb.cooldownMs)
                continue;
        }
        return pb;
    }
    return null;
}
exports.matchPlaybook = matchPlaybook;
/**
 * Execute a playbook. Steps run sequentially; each step is simulated
 * (actual fleet integration would call real APIs).
 */
function executePlaybook(playbookId, triggeredBy, triggerAlert) {
    return __awaiter(this, void 0, void 0, function () {
        var pb, execution;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    ensureDefaults();
                    pb = playbooks.find(function (p) { return p.id === playbookId; });
                    if (!pb) {
                        throw new Error("Playbook not found: ".concat(playbookId));
                    }
                    execution = {
                        id: makeExecutionId(),
                        playbookId: pb.id,
                        playbookName: pb.name,
                        triggeredBy: triggeredBy,
                        triggerAlert: triggerAlert,
                        status: pb.requiresApproval ? 'pending_approval' : 'executing',
                        steps: pb.steps.map(function (step) { return ({ step: step, status: 'pending' }); }),
                        startedAt: new Date().toISOString()
                    };
                    executions.unshift(execution);
                    // If requires approval, stop here -- wait for approveExecution()
                    if (pb.requiresApproval) {
                        return [2 /*return*/, execution];
                    }
                    // Execute immediately
                    return [4 /*yield*/, runExecutionSteps(execution, pb)];
                case 1:
                    // Execute immediately
                    _a.sent();
                    return [2 /*return*/, execution];
            }
        });
    });
}
exports.executePlaybook = executePlaybook;
function runExecutionSteps(execution, pb) {
    var _a;
    return __awaiter(this, void 0, void 0, function () {
        var _i, _b, stepEntry, e_1;
        return __generator(this, function (_c) {
            switch (_c.label) {
                case 0:
                    execution.status = 'executing';
                    _i = 0, _b = execution.steps;
                    _c.label = 1;
                case 1:
                    if (!(_i < _b.length)) return [3 /*break*/, 6];
                    stepEntry = _b[_i];
                    if (execution.status === 'aborted') {
                        stepEntry.status = 'skipped';
                        return [3 /*break*/, 5];
                    }
                    stepEntry.status = 'running';
                    _c.label = 2;
                case 2:
                    _c.trys.push([2, 4, , 5]);
                    // Simulate step execution with a brief delay
                    return [4 /*yield*/, new Promise(function (resolve) { return setTimeout(resolve, 50); })];
                case 3:
                    // Simulate step execution with a brief delay
                    _c.sent();
                    switch (stepEntry.step.type) {
                        case 'toggle_feature':
                            stepEntry.result = { action: 'feature_toggled', flag: 'last_deployed', state: 'disabled' };
                            break;
                        case 'notify':
                            stepEntry.result = { action: 'notification_sent', channel: 'ops', message: stepEntry.step.description };
                            break;
                        case 'revert_deploy':
                            stepEntry.result = { action: 'deploy_reverted', target: 'last_known_good' };
                            break;
                        case 'scale':
                            stepEntry.result = { action: 'scaled', direction: ((_a = stepEntry.step.payload) === null || _a === void 0 ? void 0 : _a.direction) || 'up' };
                            break;
                        case 'fleet_execute':
                            stepEntry.result = { action: 'fleet_command_sent', app: stepEntry.step.app, command: stepEntry.step.action };
                            break;
                        case 'custom':
                            stepEntry.result = { action: stepEntry.step.action || 'custom_executed', description: stepEntry.step.description };
                            break;
                    }
                    stepEntry.status = 'completed';
                    return [3 /*break*/, 5];
                case 4:
                    e_1 = _c.sent();
                    stepEntry.status = 'failed';
                    stepEntry.error = e_1.message || 'Step execution failed';
                    execution.status = 'failed';
                    execution.completedAt = new Date().toISOString();
                    return [2 /*return*/];
                case 5:
                    _i++;
                    return [3 /*break*/, 1];
                case 6:
                    execution.status = 'completed';
                    execution.completedAt = new Date().toISOString();
                    // Update playbook stats
                    pb.lastExecutedAt = execution.startedAt;
                    pb.executionCount++;
                    return [2 /*return*/];
            }
        });
    });
}
/**
 * Approve a pending execution and start running its steps.
 */
function approveExecution(executionId) {
    return __awaiter(this, void 0, void 0, function () {
        var execution, pb;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    execution = executions.find(function (e) { return e.id === executionId; });
                    if (!execution) {
                        throw new Error("Execution not found: ".concat(executionId));
                    }
                    if (execution.status !== 'pending_approval') {
                        throw new Error("Execution is not pending approval (status: ".concat(execution.status, ")"));
                    }
                    pb = playbooks.find(function (p) { return p.id === execution.playbookId; });
                    if (!pb) {
                        throw new Error("Playbook not found: ".concat(execution.playbookId));
                    }
                    return [4 /*yield*/, runExecutionSteps(execution, pb)];
                case 1:
                    _a.sent();
                    return [2 /*return*/, execution];
            }
        });
    });
}
exports.approveExecution = approveExecution;
/**
 * Abort a pending or executing execution.
 */
function abortExecution(executionId) {
    var execution = executions.find(function (e) { return e.id === executionId; });
    if (!execution) {
        throw new Error("Execution not found: ".concat(executionId));
    }
    execution.status = 'aborted';
    execution.completedAt = new Date().toISOString();
    for (var _i = 0, _a = execution.steps; _i < _a.length; _i++) {
        var step = _a[_i];
        if (step.status === 'pending' || step.status === 'running') {
            step.status = 'skipped';
        }
    }
    return execution;
}
exports.abortExecution = abortExecution;
/**
 * Get all playbooks.
 */
function getPlaybooks() {
    ensureDefaults();
    return __spreadArray([], playbooks, true);
}
exports.getPlaybooks = getPlaybooks;
/**
 * Get execution history.
 */
function getExecutionHistory() {
    return __spreadArray([], executions, true);
}
exports.getExecutionHistory = getExecutionHistory;
/**
 * Update a playbook's settings.
 */
function updatePlaybook(id, updates) {
    ensureDefaults();
    var pb = playbooks.find(function (p) { return p.id === id; });
    if (!pb) {
        throw new Error("Playbook not found: ".concat(id));
    }
    if (updates.enabled !== undefined)
        pb.enabled = updates.enabled;
    if (updates.name !== undefined)
        pb.name = updates.name;
    if (updates.description !== undefined)
        pb.description = updates.description;
    if (updates.requiresApproval !== undefined)
        pb.requiresApproval = updates.requiresApproval;
    if (updates.cooldownMs !== undefined)
        pb.cooldownMs = updates.cooldownMs;
    if (updates.steps !== undefined)
        pb.steps = updates.steps;
    if (updates.trigger !== undefined)
        pb.trigger = __assign(__assign({}, pb.trigger), updates.trigger);
    return __assign({}, pb);
}
exports.updatePlaybook = updatePlaybook;
/**
 * Create a new playbook.
 */
function createPlaybook(input) {
    ensureDefaults();
    var pb = __assign(__assign({}, input), { id: "pb-".concat(Date.now(), "-").concat(Math.random().toString(36).slice(2, 6)), executionCount: 0 });
    playbooks.push(pb);
    return __assign({}, pb);
}
exports.createPlaybook = createPlaybook;
/**
 * Process an anomaly alert: check for matching playbook and auto-execute or queue.
 */
function processAnomalyAlert(alert) {
    return __awaiter(this, void 0, void 0, function () {
        var pb;
        return __generator(this, function (_a) {
            pb = matchPlaybook(alert);
            if (!pb)
                return [2 /*return*/, null];
            return [2 /*return*/, executePlaybook(pb.id, alert.id, alert)];
        });
    });
}
exports.processAnomalyAlert = processAnomalyAlert;
