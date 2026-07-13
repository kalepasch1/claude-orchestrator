"use strict";
/**
 * Prompt-Driven Ops — processes PROMPT-*.md files as admin commands.
 * Integrates with the existing intake_watcher pattern from the orchestrator's Python runner.
 *
 * When a PROMPT file is detected, it:
 * 1. Parses the markdown for intent (using Claude)
 * 2. Maps intent to proxy API calls or fleet execute commands
 * 3. Executes with the same approval flow as NL Admin
 * 4. Writes results back to a RESULT-*.md file
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
exports.approveAndExecute = exports.getPromptOp = exports.listPromptOps = exports.processPromptFile = exports.executePromptOp = exports.parsePromptFile = void 0;
var sdk_1 = require("@anthropic-ai/sdk");
// In-memory prompt ops store
var promptOps = [];
function generateId() {
    return "prompt-".concat(Date.now(), "-").concat(Math.random().toString(36).slice(2, 8));
}
var PARSE_SYSTEM = "You are an operations command parser for the SMRTER fleet orchestrator.\nGiven a prompt-ops markdown file, extract:\n1. The operator's intent (a concise summary)\n2. A list of API actions to execute\n\nAvailable API endpoints:\n- GET /api/proxy/apps \u2014 list all apps\n- GET /api/proxy/{app}/users \u2014 list users for an app\n- POST /api/proxy/{app}/query \u2014 query a database table (body: { table, select?, filters?, limit? })\n- POST /api/proxy/{app}/execute \u2014 execute a fleet action (body: { action: { type, ... } })\n- GET /api/fleet/incidents \u2014 list fleet incidents\n- GET /api/fleet/policies \u2014 list auto-policies\n- POST /api/fleet/policies \u2014 create a policy\n- GET /api/admin/deploys \u2014 deploy history\n- POST /api/admin/deploys/create \u2014 create a deploy plan\n\nRespond with JSON only (no markdown fences):\n{\n  \"intent\": \"short summary of what the operator wants\",\n  \"actions\": [\n    { \"endpoint\": \"/api/...\", \"method\": \"GET|POST\", \"body\": {...} or null, \"description\": \"what this does\" }\n  ]\n}";
function parsePromptFile(content) {
    return __awaiter(this, void 0, void 0, function () {
        var apiKey, client, response, text, parsed, e_1;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    apiKey = process.env.ANTHROPIC_API_KEY;
                    if (!apiKey) {
                        return [2 /*return*/, {
                                intent: 'Could not parse — ANTHROPIC_API_KEY not configured',
                                actions: []
                            }];
                    }
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, 3, , 4]);
                    client = new sdk_1["default"]({ apiKey: apiKey });
                    return [4 /*yield*/, client.messages.create({
                            model: 'claude-sonnet-4-20250514',
                            max_tokens: 2048,
                            system: PARSE_SYSTEM,
                            messages: [{ role: 'user', content: content }]
                        })];
                case 2:
                    response = _a.sent();
                    text = response.content
                        .filter(function (b) { return b.type === 'text'; })
                        .map(function (b) { return b.text; })
                        .join('');
                    parsed = JSON.parse(text);
                    return [2 /*return*/, {
                            intent: parsed.intent || 'Unknown intent',
                            actions: Array.isArray(parsed.actions) ? parsed.actions : []
                        }];
                case 3:
                    e_1 = _a.sent();
                    return [2 /*return*/, {
                            intent: "Parse error: ".concat(e_1.message),
                            actions: []
                        }];
                case 4: return [2 /*return*/];
            }
        });
    });
}
exports.parsePromptFile = parsePromptFile;
function executePromptOp(op) {
    return __awaiter(this, void 0, void 0, function () {
        var results, _i, _a, action, fetchOptions, result, e_2;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    if (!op.actions || op.actions.length === 0) {
                        op.status = 'failed';
                        op.error = 'No actions to execute';
                        op.completedAt = new Date().toISOString();
                        return [2 /*return*/, op];
                    }
                    op.status = 'executing';
                    results = [];
                    _i = 0, _a = op.actions;
                    _b.label = 1;
                case 1:
                    if (!(_i < _a.length)) return [3 /*break*/, 6];
                    action = _a[_i];
                    _b.label = 2;
                case 2:
                    _b.trys.push([2, 4, , 5]);
                    fetchOptions = {
                        method: action.method
                    };
                    if (action.body && action.method !== 'GET') {
                        fetchOptions.body = action.body;
                    }
                    return [4 /*yield*/, $fetch(action.endpoint, fetchOptions)];
                case 3:
                    result = _b.sent();
                    results.push("[OK] ".concat(action.description || action.endpoint, ": ").concat(JSON.stringify(result).slice(0, 500)));
                    return [3 /*break*/, 5];
                case 4:
                    e_2 = _b.sent();
                    results.push("[ERR] ".concat(action.description || action.endpoint, ": ").concat(e_2.message || String(e_2)));
                    return [3 /*break*/, 5];
                case 5:
                    _i++;
                    return [3 /*break*/, 1];
                case 6:
                    op.result = results.join('\n\n');
                    op.status = 'complete';
                    op.completedAt = new Date().toISOString();
                    return [2 /*return*/, op];
            }
        });
    });
}
exports.executePromptOp = executePromptOp;
function processPromptFile(filename, content) {
    return __awaiter(this, void 0, void 0, function () {
        var op, _a, intent, actions;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    op = {
                        id: generateId(),
                        filename: filename,
                        content: content,
                        status: 'pending',
                        createdAt: new Date().toISOString()
                    };
                    promptOps.unshift(op);
                    return [4 /*yield*/, parsePromptFile(content)];
                case 1:
                    _a = _b.sent(), intent = _a.intent, actions = _a.actions;
                    op.intent = intent;
                    op.actions = actions;
                    op.status = 'parsed';
                    return [2 /*return*/, op];
            }
        });
    });
}
exports.processPromptFile = processPromptFile;
function listPromptOps() {
    return promptOps;
}
exports.listPromptOps = listPromptOps;
function getPromptOp(id) {
    return promptOps.find(function (op) { return op.id === id; });
}
exports.getPromptOp = getPromptOp;
function approveAndExecute(id) {
    return __awaiter(this, void 0, void 0, function () {
        var op;
        return __generator(this, function (_a) {
            op = promptOps.find(function (o) { return o.id === id; });
            if (!op)
                throw new Error("Prompt op ".concat(id, " not found"));
            if (op.status !== 'parsed')
                throw new Error("Op ".concat(id, " is not in parsed state (status: ").concat(op.status, ")"));
            op.status = 'approved';
            return [2 /*return*/, executePromptOp(op)];
        });
    });
}
exports.approveAndExecute = approveAndExecute;
