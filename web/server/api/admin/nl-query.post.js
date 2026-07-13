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
var sdk_1 = require("@anthropic-ai/sdk");
var SYSTEM_PROMPT = "You are an admin assistant for the SMRTER fleet orchestrator. You help operators query data across all managed apps.\n\nAvailable apps: apparently, tomorrow, smarter, galop, hisanta, pareto, orchestrator\n\nYou have tools to query the proxy API layer. Use them to answer the operator's question, then summarize the results clearly.\n\nWhen presenting data:\n- Use markdown tables for tabular results\n- Show counts and totals when relevant\n- Highlight important findings\n- If a query returns no data, say so clearly\n- If a question is ambiguous, make your best interpretation and note your assumption";
var TOOLS = [
    {
        name: 'list_apps',
        description: 'List all configured apps in the fleet with their status',
        input_schema: { type: 'object', properties: {}, required: [] }
    },
    {
        name: 'query_table',
        description: 'Query any database table in a specific app. Use this for data exploration.',
        input_schema: {
            type: 'object',
            properties: {
                app: { type: 'string', description: 'App ID: apparently, tomorrow, smarter, galop, hisanta, pareto, orchestrator' },
                table: { type: 'string', description: 'Table name to query' },
                select: { type: 'string', description: 'Columns to select (default: *)' },
                filters: {
                    type: 'array',
                    description: 'Array of filter objects',
                    items: {
                        type: 'object',
                        properties: {
                            column: { type: 'string' },
                            op: { type: 'string', "enum": ['eq', 'neq', 'gt', 'lt', 'gte', 'lte', 'like', 'ilike', 'in'] },
                            value: {}
                        },
                        required: ['column', 'op', 'value']
                    }
                },
                order: {
                    type: 'object',
                    properties: {
                        column: { type: 'string' },
                        ascending: { type: 'boolean' }
                    }
                },
                limit: { type: 'number', description: 'Max rows to return (default: 50)' }
            },
            required: ['app', 'table']
        }
    },
    {
        name: 'list_app_users',
        description: 'List or search users in a specific app. Optionally filter by email.',
        input_schema: {
            type: 'object',
            properties: {
                app: { type: 'string', description: 'App ID' },
                email: { type: 'string', description: 'Optional email filter (partial match)' },
                limit: { type: 'number', description: 'Max users (default: 50)' }
            },
            required: ['app']
        }
    },
    {
        name: 'cross_app_user_search',
        description: 'Search for a user by exact email across ALL apps. Returns which apps they have accounts in.',
        input_schema: {
            type: 'object',
            properties: {
                email: { type: 'string', description: 'Exact email address to search' }
            },
            required: ['email']
        }
    },
    {
        name: 'list_fleet_events',
        description: 'Get recent fleet events/incidents across all apps. Returns correlated incidents.',
        input_schema: {
            type: 'object',
            properties: {
                windowMin: { type: 'number', description: 'Correlation window in minutes (default: 15)' }
            }
        }
    },
    {
        name: 'list_policies',
        description: 'List all auto-resolution policies in the fleet.',
        input_schema: { type: 'object', properties: {}, required: [] }
    },
    {
        name: 'execute_fleet_action',
        description: 'Execute a fleet action on a specific app (e.g., disable user, run migration). Use with caution.',
        input_schema: {
            type: 'object',
            properties: {
                app: { type: 'string', description: 'App ID' },
                action: { type: 'object', description: 'Action payload to execute' }
            },
            required: ['app', 'action']
        }
    },
    {
        name: 'list_tables',
        description: 'List available tables in a specific app database.',
        input_schema: {
            type: 'object',
            properties: {
                app: { type: 'string', description: 'App ID' }
            },
            required: ['app']
        }
    },
];
function executeTool(toolName, input) {
    var _a;
    return __awaiter(this, void 0, void 0, function () {
        var _b, e_1;
        return __generator(this, function (_c) {
            switch (_c.label) {
                case 0:
                    _c.trys.push([0, 19, , 20]);
                    _b = toolName;
                    switch (_b) {
                        case 'list_apps': return [3 /*break*/, 1];
                        case 'query_table': return [3 /*break*/, 3];
                        case 'list_app_users': return [3 /*break*/, 5];
                        case 'cross_app_user_search': return [3 /*break*/, 7];
                        case 'list_fleet_events': return [3 /*break*/, 9];
                        case 'list_policies': return [3 /*break*/, 11];
                        case 'execute_fleet_action': return [3 /*break*/, 13];
                        case 'list_tables': return [3 /*break*/, 15];
                    }
                    return [3 /*break*/, 17];
                case 1: return [4 /*yield*/, $fetch('/api/proxy/apps')];
                case 2: return [2 /*return*/, _c.sent()];
                case 3: return [4 /*yield*/, $fetch("/api/proxy/".concat(input.app, "/query"), {
                        method: 'POST',
                        body: {
                            table: input.table,
                            select: input.select,
                            filters: input.filters,
                            order: input.order,
                            limit: (_a = input.limit) !== null && _a !== void 0 ? _a : 50
                        }
                    })];
                case 4: return [2 /*return*/, _c.sent()];
                case 5: return [4 /*yield*/, $fetch("/api/proxy/".concat(input.app, "/users"), {
                        params: { email: input.email, limit: input.limit }
                    })];
                case 6: return [2 /*return*/, _c.sent()];
                case 7: return [4 /*yield*/, $fetch('/api/proxy/cross-app/users', {
                        params: { email: input.email }
                    })];
                case 8: return [2 /*return*/, _c.sent()];
                case 9: return [4 /*yield*/, $fetch('/api/fleet/incidents', {
                        params: { windowMin: input.windowMin }
                    })];
                case 10: return [2 /*return*/, _c.sent()];
                case 11: return [4 /*yield*/, $fetch('/api/fleet/policies')];
                case 12: return [2 /*return*/, _c.sent()];
                case 13: return [4 /*yield*/, $fetch("/api/proxy/".concat(input.app, "/execute"), {
                        method: 'POST',
                        body: { action: input.action }
                    })];
                case 14: return [2 /*return*/, _c.sent()];
                case 15: return [4 /*yield*/, $fetch("/api/proxy/".concat(input.app, "/tables"))];
                case 16: return [2 /*return*/, _c.sent()];
                case 17: return [2 /*return*/, { error: "Unknown tool: ".concat(toolName) }];
                case 18: return [3 /*break*/, 20];
                case 19:
                    e_1 = _c.sent();
                    return [2 /*return*/, { error: e_1.message || String(e_1) }];
                case 20: return [2 /*return*/];
            }
        });
    });
}
exports["default"] = defineEventHandler(function (event) { return __awaiter(void 0, void 0, void 0, function () {
    var body, apiKey, client, messages, _i, _a, msg, currentMessages, allData, iterations, MAX_ITERATIONS, response, toolResults, _b, _c, block, result, textBlocks, responseText, e_2;
    var _d;
    return __generator(this, function (_e) {
        switch (_e.label) {
            case 0: return [4 /*yield*/, readBody(event)];
            case 1:
                body = _e.sent();
                if (!((_d = body === null || body === void 0 ? void 0 : body.query) === null || _d === void 0 ? void 0 : _d.trim())) {
                    throw createError({ statusCode: 400, message: 'query is required' });
                }
                apiKey = process.env.ANTHROPIC_API_KEY;
                if (!apiKey) {
                    throw createError({ statusCode: 500, message: 'ANTHROPIC_API_KEY not configured' });
                }
                client = new sdk_1["default"]({ apiKey: apiKey });
                messages = [];
                if (body.history) {
                    for (_i = 0, _a = body.history; _i < _a.length; _i++) {
                        msg = _a[_i];
                        if (msg.role === 'user' || msg.role === 'assistant') {
                            messages.push({ role: msg.role, content: msg.content });
                        }
                    }
                }
                messages.push({ role: 'user', content: body.query });
                _e.label = 2;
            case 2:
                _e.trys.push([2, 12, , 13]);
                currentMessages = __spreadArray([], messages, true);
                allData = [];
                iterations = 0;
                MAX_ITERATIONS = 10;
                _e.label = 3;
            case 3:
                if (!(iterations < MAX_ITERATIONS)) return [3 /*break*/, 11];
                iterations++;
                return [4 /*yield*/, client.messages.create({
                        model: 'claude-sonnet-4-20250514',
                        max_tokens: 4096,
                        system: SYSTEM_PROMPT,
                        tools: TOOLS,
                        messages: currentMessages
                    })
                    // Check if Claude wants to use tools
                ];
            case 4:
                response = _e.sent();
                if (!(response.stop_reason === 'tool_use')) return [3 /*break*/, 9];
                // Add the assistant message with tool_use blocks
                currentMessages.push({ role: 'assistant', content: response.content });
                toolResults = [];
                _b = 0, _c = response.content;
                _e.label = 5;
            case 5:
                if (!(_b < _c.length)) return [3 /*break*/, 8];
                block = _c[_b];
                if (!(block.type === 'tool_use')) return [3 /*break*/, 7];
                return [4 /*yield*/, executeTool(block.name, block.input)];
            case 6:
                result = _e.sent();
                if (result && !result.error) {
                    allData.push({ tool: block.name, input: block.input, result: result });
                }
                toolResults.push({
                    type: 'tool_result',
                    tool_use_id: block.id,
                    content: JSON.stringify(result)
                });
                _e.label = 7;
            case 7:
                _b++;
                return [3 /*break*/, 5];
            case 8:
                currentMessages.push({ role: 'user', content: toolResults });
                return [3 /*break*/, 10];
            case 9:
                textBlocks = response.content.filter(function (b) { return b.type === 'text'; });
                responseText = textBlocks.map(function (b) { return b.text; }).join('\n');
                return [2 /*return*/, {
                        response: responseText,
                        data: allData.length > 0 ? allData : undefined,
                        toolCalls: iterations - 1
                    }];
            case 10: return [3 /*break*/, 3];
            case 11: 
            // If we hit max iterations, return what we have
            return [2 /*return*/, {
                    response: 'I ran into the maximum number of tool calls. Here is what I found so far.',
                    data: allData.length > 0 ? allData : undefined,
                    toolCalls: iterations
                }];
            case 12:
                e_2 = _e.sent();
                console.error('NL query error:', e_2);
                throw createError({
                    statusCode: 500,
                    message: e_2.message || 'Failed to process query'
                });
            case 13: return [2 /*return*/];
        }
    });
}); });
