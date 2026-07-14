"use strict";
/**
 * Admin Action Replay — records admin sessions as replayable scripts.
 * Captures NL Admin queries, proxy API calls, fleet executions, and policy decisions
 * as an ordered sequence that can be replayed, shared, or scheduled.
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
exports.generateOnboardingTemplate = exports.generateAuditTemplate = exports.generateIncidentResponseTemplate = exports.cloneRecording = exports.tagRecording = exports.deleteRecording = exports.getRecording = exports.getRecordings = exports.replayRecording = exports.getActiveRecording = exports.stopRecording = exports.addAction = exports.startRecording = void 0;
// In-memory state
var recordings = new Map();
var activeRecordingId = null;
function generateId() {
    return 'rec-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
}
// ---------- Recording lifecycle ----------
function startRecording(name, description, createdBy) {
    if (activeRecordingId) {
        // Auto-stop any existing active recording
        stopRecording(activeRecordingId);
    }
    var recording = {
        id: generateId(),
        name: name,
        description: description,
        createdBy: createdBy,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        actions: [],
        tags: [],
        replayCount: 0,
        status: 'recording'
    };
    recordings.set(recording.id, recording);
    activeRecordingId = recording.id;
    return recording;
}
exports.startRecording = startRecording;
function addAction(recordingId, action) {
    var recording = recordings.get(recordingId);
    if (!recording || recording.status !== 'recording')
        return;
    var seq = recording.actions.length + 1;
    recording.actions.push(__assign(__assign({}, action), { seq: seq }));
    recording.updatedAt = new Date().toISOString();
}
exports.addAction = addAction;
function stopRecording(recordingId) {
    var recording = recordings.get(recordingId);
    if (!recording)
        return null;
    recording.status = 'saved';
    recording.updatedAt = new Date().toISOString();
    if (activeRecordingId === recordingId) {
        activeRecordingId = null;
    }
    return recording;
}
exports.stopRecording = stopRecording;
function getActiveRecording() {
    if (!activeRecordingId)
        return null;
    return recordings.get(activeRecordingId) || null;
}
exports.getActiveRecording = getActiveRecording;
// ---------- Replay ----------
function replayRecording(recordingId, options) {
    var _a, _b;
    return __awaiter(this, void 0, void 0, function () {
        var recording, dryRun, skipExecutes, replayStart, replayActions, _i, _c, action, actionStart, replayOutput, error, matched, _d, resp, resp, resp, resp, resp, e_1, matchCount, overallMatch;
        return __generator(this, function (_e) {
            switch (_e.label) {
                case 0:
                    recording = recordings.get(recordingId);
                    if (!recording) {
                        throw new Error("Recording ".concat(recordingId, " not found"));
                    }
                    dryRun = (_a = options === null || options === void 0 ? void 0 : options.dryRun) !== null && _a !== void 0 ? _a : false;
                    skipExecutes = (_b = options === null || options === void 0 ? void 0 : options.skipExecutes) !== null && _b !== void 0 ? _b : false;
                    replayStart = Date.now();
                    replayActions = [];
                    _i = 0, _c = recording.actions;
                    _e.label = 1;
                case 1:
                    if (!(_i < _c.length)) return [3 /*break*/, 28];
                    action = _c[_i];
                    actionStart = Date.now();
                    replayOutput = null;
                    error = void 0;
                    matched = false;
                    _e.label = 2;
                case 2:
                    _e.trys.push([2, 25, , 26]);
                    _d = action.type;
                    switch (_d) {
                        case 'nl_query': return [3 /*break*/, 3];
                        case 'proxy_query': return [3 /*break*/, 7];
                        case 'fleet_execute': return [3 /*break*/, 11];
                        case 'policy_decision': return [3 /*break*/, 15];
                        case 'approval': return [3 /*break*/, 16];
                        case 'playbook_trigger': return [3 /*break*/, 20];
                    }
                    return [3 /*break*/, 24];
                case 3:
                    if (!dryRun) return [3 /*break*/, 4];
                    replayOutput = { dryRun: true, wouldPost: '/api/admin/nl-query', input: action.input };
                    return [3 /*break*/, 6];
                case 4: return [4 /*yield*/, $fetch('/api/admin/nl-query', {
                        method: 'POST',
                        body: action.input
                    })["catch"](function (e) { return ({ error: e.message }); })];
                case 5:
                    resp = _e.sent();
                    replayOutput = resp;
                    _e.label = 6;
                case 6: return [3 /*break*/, 24];
                case 7:
                    if (!dryRun) return [3 /*break*/, 8];
                    replayOutput = { dryRun: true, wouldPost: "/api/proxy/".concat(action.app, "/query"), input: action.input };
                    return [3 /*break*/, 10];
                case 8: return [4 /*yield*/, $fetch("/api/proxy/".concat(action.app, "/query"), {
                        method: 'POST',
                        body: action.input
                    })["catch"](function (e) { return ({ error: e.message }); })];
                case 9:
                    resp = _e.sent();
                    replayOutput = resp;
                    _e.label = 10;
                case 10: return [3 /*break*/, 24];
                case 11:
                    if (!(dryRun || skipExecutes)) return [3 /*break*/, 12];
                    replayOutput = { skipped: true, reason: dryRun ? 'dry_run' : 'skip_executes', input: action.input };
                    return [3 /*break*/, 14];
                case 12: return [4 /*yield*/, $fetch("/api/proxy/".concat(action.app, "/execute"), {
                        method: 'POST',
                        body: action.input
                    })["catch"](function (e) { return ({ error: e.message }); })];
                case 13:
                    resp = _e.sent();
                    replayOutput = resp;
                    _e.label = 14;
                case 14: return [3 /*break*/, 24];
                case 15:
                    {
                        replayOutput = { type: 'policy_comparison', input: action.input, note: 'Policy engine comparison' };
                        return [3 /*break*/, 24];
                    }
                    _e.label = 16;
                case 16:
                    if (!dryRun) return [3 /*break*/, 17];
                    replayOutput = { dryRun: true, wouldPost: '/api/approvals/decide', input: action.input };
                    return [3 /*break*/, 19];
                case 17: return [4 /*yield*/, $fetch('/api/approvals/decide', {
                        method: 'POST',
                        body: action.input
                    })["catch"](function (e) { return ({ error: e.message }); })];
                case 18:
                    resp = _e.sent();
                    replayOutput = resp;
                    _e.label = 19;
                case 19: return [3 /*break*/, 24];
                case 20:
                    if (!dryRun) return [3 /*break*/, 21];
                    replayOutput = { dryRun: true, wouldPost: '/api/admin/playbooks/execute', input: action.input };
                    return [3 /*break*/, 23];
                case 21: return [4 /*yield*/, $fetch('/api/admin/playbooks/execute', {
                        method: 'POST',
                        body: action.input
                    })["catch"](function (e) { return ({ error: e.message }); })];
                case 22:
                    resp = _e.sent();
                    replayOutput = resp;
                    _e.label = 23;
                case 23: return [3 /*break*/, 24];
                case 24:
                    // Simple output comparison — check for structural similarity
                    matched = compareOutputs(action.output, replayOutput);
                    return [3 /*break*/, 26];
                case 25:
                    e_1 = _e.sent();
                    error = e_1.message || 'Unknown replay error';
                    matched = false;
                    return [3 /*break*/, 26];
                case 26:
                    replayActions.push({
                        seq: action.seq,
                        originalOutput: action.output,
                        replayOutput: replayOutput,
                        matched: matched,
                        duration_ms: Date.now() - actionStart,
                        error: error
                    });
                    _e.label = 27;
                case 27:
                    _i++;
                    return [3 /*break*/, 1];
                case 28:
                    // Update recording stats
                    recording.replayCount++;
                    recording.lastReplayedAt = new Date().toISOString();
                    matchCount = replayActions.filter(function (a) { return a.matched; }).length;
                    overallMatch = replayActions.length > 0 ? Math.round((matchCount / replayActions.length) * 100) : 100;
                    return [2 /*return*/, {
                            recordingId: recordingId,
                            replayedAt: new Date().toISOString(),
                            actions: replayActions,
                            overallMatch: overallMatch,
                            duration_ms: Date.now() - replayStart
                        }];
            }
        });
    });
}
exports.replayRecording = replayRecording;
function compareOutputs(original, replay) {
    if (original === undefined || original === null)
        return true; // No original to compare against
    if ((replay === null || replay === void 0 ? void 0 : replay.dryRun) || (replay === null || replay === void 0 ? void 0 : replay.skipped))
        return true; // Can't compare dry runs
    if (replay === null || replay === void 0 ? void 0 : replay.error)
        return false;
    try {
        // Check if both have same top-level keys
        if (typeof original === 'object' && typeof replay === 'object') {
            var origKeys = Object.keys(original).sort();
            var replayKeys_1 = Object.keys(replay).sort();
            // If they share at least 50% of keys, consider it a match
            var shared = origKeys.filter(function (k) { return replayKeys_1.includes(k); });
            return shared.length >= origKeys.length * 0.5;
        }
        return String(original) === String(replay);
    }
    catch (_a) {
        return false;
    }
}
// ---------- Management ----------
function getRecordings(tags) {
    var all = Array.from(recordings.values());
    if (!tags || tags.length === 0)
        return all;
    return all.filter(function (r) { return tags.some(function (t) { return r.tags.includes(t); }); });
}
exports.getRecordings = getRecordings;
function getRecording(id) {
    return recordings.get(id) || null;
}
exports.getRecording = getRecording;
function deleteRecording(id) {
    if (activeRecordingId === id) {
        activeRecordingId = null;
    }
    recordings["delete"](id);
}
exports.deleteRecording = deleteRecording;
function tagRecording(id, tags) {
    var recording = recordings.get(id);
    if (!recording)
        return;
    recording.tags = __spreadArray([], new Set(__spreadArray(__spreadArray([], recording.tags, true), tags, true)), true);
    recording.updatedAt = new Date().toISOString();
}
exports.tagRecording = tagRecording;
function cloneRecording(id, newName) {
    var original = recordings.get(id);
    if (!original)
        return null;
    var clone = __assign(__assign({}, original), { id: generateId(), name: newName, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), actions: JSON.parse(JSON.stringify(original.actions)), tags: __spreadArray([], original.tags, true), replayCount: 0, lastReplayedAt: undefined, status: 'saved' });
    recordings.set(clone.id, clone);
    return clone;
}
exports.cloneRecording = cloneRecording;
// ---------- Templates ----------
function generateIncidentResponseTemplate() {
    var id = generateId();
    var template = {
        id: id,
        name: 'Incident Response',
        description: 'Standard incident response: check health, scan anomalies, review predictions, run playbook',
        createdBy: 'system',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        tags: ['incident-response', 'template'],
        replayCount: 0,
        status: 'saved',
        actions: [
            { seq: 1, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Show fleet health status for all apps' } },
            { seq: 2, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Scan for anomalies across all apps in the last hour' } },
            { seq: 3, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Show predictive incident analysis' } },
            { seq: 4, type: 'playbook_trigger', timestamp: new Date().toISOString(), input: { playbookId: 'pb-error-spike', reason: 'Incident response template' } },
        ]
    };
    recordings.set(id, template);
    return template;
}
exports.generateIncidentResponseTemplate = generateIncidentResponseTemplate;
function generateAuditTemplate() {
    var id = generateId();
    var template = {
        id: id,
        name: 'Compliance Audit',
        description: 'Standard audit: generate regulatory snapshot, review compliance graph, export report',
        createdBy: 'system',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        tags: ['audit', 'compliance', 'template'],
        replayCount: 0,
        status: 'saved',
        actions: [
            { seq: 1, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Generate regulatory compliance snapshot for all apps' } },
            { seq: 2, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Show compliance dependency graph' } },
            { seq: 3, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Export compliance report' } },
        ]
    };
    recordings.set(id, template);
    return template;
}
exports.generateAuditTemplate = generateAuditTemplate;
function generateOnboardingTemplate() {
    var id = generateId();
    var template = {
        id: id,
        name: 'User Onboarding Verification',
        description: 'Verify new user setup: cross-app search, check workspace, verify permissions',
        createdBy: 'system',
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        tags: ['onboarding', 'template'],
        replayCount: 0,
        status: 'saved',
        actions: [
            { seq: 1, type: 'proxy_query', timestamp: new Date().toISOString(), input: { query: 'Search for user across all apps' }, app: 'orchestrator' },
            { seq: 2, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Check workspace configuration for new user' } },
            { seq: 3, type: 'nl_query', timestamp: new Date().toISOString(), input: { query: 'Verify user permissions across all apps' } },
        ]
    };
    recordings.set(id, template);
    return template;
}
exports.generateOnboardingTemplate = generateOnboardingTemplate;
