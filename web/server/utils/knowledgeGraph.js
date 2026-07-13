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
exports.getAllEdges = exports.getAllNodes = exports.getNode = exports.getGraphStats = exports.findPaths = exports.searchGraph = exports.buildEntitySubgraph = exports.buildUserSubgraph = exports.CROSS_APP_RELATIONSHIPS = void 0;
/**
 * Fleet Knowledge Graph — semantic entity graph across all apps.
 * Connects users, documents, transactions, features, and compliance items
 * across the fleet. Enables "show me everything related to user X" queries
 * that trace through auth, billing, compliance, and content in one query.
 */
var appClients_1 = require("./appClients");
// ── Predefined relationship templates ──────────────────────────────────
exports.CROSS_APP_RELATIONSHIPS = [
    { pattern: 'user_identity', description: 'Same user across apps linked by email' },
    { pattern: 'onboarding_chain', apps: ['apparently', 'smarter', 'tomorrow'], description: 'Client onboarding flows through compliance -> workspace -> trading' },
    { pattern: 'compliance_cascade', description: 'Compliance action in one app triggers reviews in others' },
    { pattern: 'revenue_flow', description: 'Billing events across apps for same customer' },
];
// ── In-memory graph store ──────────────────────────────────────────────
var nodeStore = new Map();
var edgeStore = new Map();
function addNode(node) {
    nodeStore.set(node.id, node);
}
function addEdge(edge) {
    edgeStore.set(edge.id, edge);
}
function makeNodeId(app, type, entityId) {
    return "".concat(app, ":").concat(type, ":").concat(entityId);
}
function makeEdgeId(source, target, relationship) {
    return "".concat(source, "->").concat(target, ":").concat(relationship);
}
// ── Graph construction helpers ─────────────────────────────────────────
function fetchUsersFromApp(appId, email) {
    var _a;
    return __awaiter(this, void 0, void 0, function () {
        var client, data, node, _b, authData, users, _c;
        return __generator(this, function (_d) {
            switch (_d.label) {
                case 0:
                    client = (0, appClients_1.getAppClient)(appId);
                    if (!client)
                        return [2 /*return*/, []];
                    _d.label = 1;
                case 1:
                    _d.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, client.rpc('get_user_by_email', { target_email: email }).maybeSingle()];
                case 2:
                    data = (_d.sent()).data;
                    if (data) {
                        node = {
                            id: makeNodeId(appId, 'user', data.id || email),
                            app: appId,
                            type: 'user',
                            entityId: data.id || email,
                            label: data.display_name || data.full_name || email,
                            properties: __assign({ email: email, role: data.role }, data),
                            lastUpdated: new Date().toISOString()
                        };
                        return [2 /*return*/, [node]];
                    }
                    return [3 /*break*/, 4];
                case 3:
                    _b = _d.sent();
                    return [3 /*break*/, 4];
                case 4:
                    _d.trys.push([4, 6, , 7]);
                    return [4 /*yield*/, client.auth.admin.listUsers({ perPage: 100 })];
                case 5:
                    authData = (_d.sent()).data;
                    users = ((_a = authData === null || authData === void 0 ? void 0 : authData.users) === null || _a === void 0 ? void 0 : _a.filter(function (u) { return u.email === email; })) || [];
                    return [2 /*return*/, users.map(function (u) {
                            var _a, _b, _c;
                            return ({
                                id: makeNodeId(appId, 'user', u.id),
                                app: appId,
                                type: 'user',
                                entityId: u.id,
                                label: ((_a = u.user_metadata) === null || _a === void 0 ? void 0 : _a.full_name) || ((_b = u.user_metadata) === null || _b === void 0 ? void 0 : _b.name) || email,
                                properties: __assign({ email: u.email, created_at: u.created_at, last_sign_in: u.last_sign_in_at, provider: (_c = u.app_metadata) === null || _c === void 0 ? void 0 : _c.provider }, u.user_metadata),
                                lastUpdated: new Date().toISOString()
                            });
                        })];
                case 6:
                    _c = _d.sent();
                    return [2 /*return*/, []];
                case 7: return [2 /*return*/];
            }
        });
    });
}
function fetchEventsForUser(appId, email) {
    return __awaiter(this, void 0, void 0, function () {
        var client, nodes, _i, _a, table, data, _b, data_1, event_1, type, node, _c;
        return __generator(this, function (_d) {
            switch (_d.label) {
                case 0:
                    client = (0, appClients_1.getAppClient)(appId);
                    if (!client)
                        return [2 /*return*/, []];
                    nodes = [];
                    _i = 0, _a = ['fleet_events', 'fleet_admin_events'];
                    _d.label = 1;
                case 1:
                    if (!(_i < _a.length)) return [3 /*break*/, 6];
                    table = _a[_i];
                    _d.label = 2;
                case 2:
                    _d.trys.push([2, 4, , 5]);
                    return [4 /*yield*/, client
                            .from(table)
                            .select('*')
                            .or("actor_email.eq.".concat(email, ",payload->>email.eq.").concat(email))
                            .order('created_at', { ascending: false })
                            .limit(20)];
                case 3:
                    data = (_d.sent()).data;
                    if (data) {
                        for (_b = 0, data_1 = data; _b < data_1.length; _b++) {
                            event_1 = data_1[_b];
                            type = categorizeEventType(event_1.event_type || event_1.action);
                            node = {
                                id: makeNodeId(appId, type, event_1.id),
                                app: appId,
                                type: type,
                                entityId: event_1.id,
                                label: "".concat(event_1.event_type || event_1.action, ": ").concat(event_1.summary || event_1.description || '').slice(0, 100),
                                properties: __assign({ event_type: event_1.event_type || event_1.action, created_at: event_1.created_at, severity: event_1.severity, status: event_1.status }, event_1.payload),
                                lastUpdated: event_1.created_at || new Date().toISOString()
                            };
                            nodes.push(node);
                        }
                    }
                    return [3 /*break*/, 5];
                case 4:
                    _c = _d.sent();
                    return [3 /*break*/, 5];
                case 5:
                    _i++;
                    return [3 /*break*/, 1];
                case 6: return [2 /*return*/, nodes];
            }
        });
    });
}
function categorizeEventType(eventType) {
    if (!eventType)
        return 'incident';
    var lower = eventType.toLowerCase();
    if (lower.includes('transaction') || lower.includes('billing') || lower.includes('payment'))
        return 'transaction';
    if (lower.includes('document') || lower.includes('upload') || lower.includes('file'))
        return 'document';
    if (lower.includes('policy') || lower.includes('compliance') || lower.includes('regulation'))
        return 'policy';
    if (lower.includes('approval') || lower.includes('approve') || lower.includes('review'))
        return 'approval';
    if (lower.includes('feature') || lower.includes('deploy') || lower.includes('release'))
        return 'feature';
    if (lower.includes('workspace') || lower.includes('project') || lower.includes('org'))
        return 'workspace';
    if (lower.includes('incident') || lower.includes('alert') || lower.includes('error'))
        return 'incident';
    return 'incident';
}
function linkCrossAppIdentities() {
    // Group user nodes by email
    var emailMap = new Map();
    for (var _i = 0, _a = nodeStore.values(); _i < _a.length; _i++) {
        var node = _a[_i];
        if (node.type === 'user') {
            var email = node.properties.email;
            if (email) {
                var list = emailMap.get(email) || [];
                list.push(node);
                emailMap.set(email, list);
            }
        }
    }
    // Create identity edges between same-email users across apps
    for (var _b = 0, emailMap_1 = emailMap; _b < emailMap_1.length; _b++) {
        var _c = emailMap_1[_b], userNodes = _c[1];
        if (userNodes.length < 2)
            continue;
        for (var i = 0; i < userNodes.length; i++) {
            for (var j = i + 1; j < userNodes.length; j++) {
                var edgeId = makeEdgeId(userNodes[i].id, userNodes[j].id, 'identity');
                if (!edgeStore.has(edgeId)) {
                    addEdge({
                        id: edgeId,
                        source: userNodes[i].id,
                        target: userNodes[j].id,
                        relationship: 'identity',
                        weight: 1.0,
                        metadata: { description: 'Same user across apps' }
                    });
                }
            }
        }
    }
}
function linkUserToEvents(userNodeId, eventNodes) {
    for (var _i = 0, eventNodes_1 = eventNodes; _i < eventNodes_1.length; _i++) {
        var event_2 = eventNodes_1[_i];
        var relationship = event_2.type === 'approval' ? 'approved'
            : event_2.type === 'incident' ? 'flagged'
                : event_2.type === 'transaction' ? 'owns'
                    : 'created_by';
        var edgeId = makeEdgeId(userNodeId, event_2.id, relationship);
        if (!edgeStore.has(edgeId)) {
            addEdge({
                id: edgeId,
                source: userNodeId,
                target: event_2.id,
                relationship: relationship,
                weight: 0.7
            });
        }
    }
}
// ── Public API ─────────────────────────────────────────────────────────
function buildUserSubgraph(email) {
    return __awaiter(this, void 0, void 0, function () {
        var allNodes, appsTraversed, userPromises, userResults, _i, userResults_1, _a, appId, users, _b, users_1, user, events, _c, events_1, event_3, nodeIds, relevantEdges, _d, _e, edge;
        var _this = this;
        return __generator(this, function (_f) {
            switch (_f.label) {
                case 0:
                    allNodes = [];
                    appsTraversed = [];
                    userPromises = appClients_1.ALL_APP_IDS.map(function (appId) { return __awaiter(_this, void 0, void 0, function () {
                        var users;
                        return __generator(this, function (_a) {
                            switch (_a.label) {
                                case 0: return [4 /*yield*/, fetchUsersFromApp(appId, email)];
                                case 1:
                                    users = _a.sent();
                                    if (users.length > 0)
                                        appsTraversed.push(appId);
                                    return [2 /*return*/, { appId: appId, users: users }];
                            }
                        });
                    }); });
                    return [4 /*yield*/, Promise.all(userPromises)];
                case 1:
                    userResults = _f.sent();
                    _i = 0, userResults_1 = userResults;
                    _f.label = 2;
                case 2:
                    if (!(_i < userResults_1.length)) return [3 /*break*/, 7];
                    _a = userResults_1[_i], appId = _a.appId, users = _a.users;
                    _b = 0, users_1 = users;
                    _f.label = 3;
                case 3:
                    if (!(_b < users_1.length)) return [3 /*break*/, 6];
                    user = users_1[_b];
                    addNode(user);
                    allNodes.push(user);
                    return [4 /*yield*/, fetchEventsForUser(appId, email)];
                case 4:
                    events = _f.sent();
                    for (_c = 0, events_1 = events; _c < events_1.length; _c++) {
                        event_3 = events_1[_c];
                        addNode(event_3);
                        allNodes.push(event_3);
                    }
                    // 3. Link user to their events
                    linkUserToEvents(user.id, events);
                    _f.label = 5;
                case 5:
                    _b++;
                    return [3 /*break*/, 3];
                case 6:
                    _i++;
                    return [3 /*break*/, 2];
                case 7:
                    // 4. Auto-detect cross-app edges
                    linkCrossAppIdentities();
                    nodeIds = new Set(allNodes.map(function (n) { return n.id; }));
                    relevantEdges = [];
                    for (_d = 0, _e = edgeStore.values(); _d < _e.length; _d++) {
                        edge = _e[_d];
                        if (nodeIds.has(edge.source) || nodeIds.has(edge.target)) {
                            relevantEdges.push(edge);
                            // Include any referenced nodes we might have missed
                            if (!nodeIds.has(edge.source) && nodeStore.has(edge.source)) {
                                allNodes.push(nodeStore.get(edge.source));
                                nodeIds.add(edge.source);
                            }
                            if (!nodeIds.has(edge.target) && nodeStore.has(edge.target)) {
                                allNodes.push(nodeStore.get(edge.target));
                                nodeIds.add(edge.target);
                            }
                        }
                    }
                    return [2 /*return*/, {
                            nodes: allNodes,
                            edges: relevantEdges,
                            stats: {
                                totalNodes: allNodes.length,
                                totalEdges: relevantEdges.length,
                                appsTraversed: __spreadArray([], new Set(appsTraversed), true)
                            }
                        }];
            }
        });
    });
}
exports.buildUserSubgraph = buildUserSubgraph;
function buildEntitySubgraph(app, type, entityId, depth) {
    if (depth === void 0) { depth = 3; }
    return __awaiter(this, void 0, void 0, function () {
        var startId, visited, queue, resultNodes, resultEdges, _a, nodeId, currentDepth, node, _i, _b, edge, neighbor, appsTraversed;
        return __generator(this, function (_c) {
            startId = makeNodeId(app, type, entityId);
            // Ensure the start node exists
            if (!nodeStore.has(startId)) {
                // Create a placeholder node
                addNode({
                    id: startId,
                    app: app,
                    type: type,
                    entityId: entityId,
                    label: "".concat(type, ":").concat(entityId),
                    properties: {},
                    lastUpdated: new Date().toISOString()
                });
            }
            visited = new Set();
            queue = [{ nodeId: startId, currentDepth: 0 }];
            resultNodes = [];
            resultEdges = [];
            while (queue.length > 0) {
                _a = queue.shift(), nodeId = _a.nodeId, currentDepth = _a.currentDepth;
                if (visited.has(nodeId) || currentDepth > depth)
                    continue;
                visited.add(nodeId);
                node = nodeStore.get(nodeId);
                if (node)
                    resultNodes.push(node);
                // Find connected edges
                for (_i = 0, _b = edgeStore.values(); _i < _b.length; _i++) {
                    edge = _b[_i];
                    if (edge.source === nodeId || edge.target === nodeId) {
                        resultEdges.push(edge);
                        neighbor = edge.source === nodeId ? edge.target : edge.source;
                        if (!visited.has(neighbor)) {
                            queue.push({ nodeId: neighbor, currentDepth: currentDepth + 1 });
                        }
                    }
                }
            }
            appsTraversed = __spreadArray([], new Set(resultNodes.map(function (n) { return n.app; })), true);
            return [2 /*return*/, {
                    nodes: resultNodes,
                    edges: resultEdges,
                    stats: {
                        totalNodes: resultNodes.length,
                        totalEdges: resultEdges.length,
                        appsTraversed: appsTraversed
                    }
                }];
        });
    });
}
exports.buildEntitySubgraph = buildEntitySubgraph;
function searchGraph(query) {
    var _a;
    return __awaiter(this, void 0, void 0, function () {
        var maxNodes, maxDepth, result, parts, result, matchingNodes, keyword, _i, _b, node, matches, searchText, nodeIds, matchingEdges, _c, _d, edge;
        return __generator(this, function (_e) {
            switch (_e.label) {
                case 0:
                    maxNodes = query.maxNodes || 50;
                    maxDepth = query.maxDepth || 3;
                    if (!query.email) return [3 /*break*/, 2];
                    return [4 /*yield*/, buildUserSubgraph(query.email)];
                case 1:
                    result = _e.sent();
                    return [2 /*return*/, filterResult(result, query, maxNodes)];
                case 2:
                    if (!query.startNode) return [3 /*break*/, 4];
                    parts = query.startNode.split(':');
                    if (!(parts.length >= 3)) return [3 /*break*/, 4];
                    return [4 /*yield*/, buildEntitySubgraph(parts[0], parts[1], parts.slice(2).join(':'), maxDepth)];
                case 3:
                    result = _e.sent();
                    return [2 /*return*/, filterResult(result, query, maxNodes)];
                case 4:
                    matchingNodes = [];
                    keyword = (_a = query.keyword) === null || _a === void 0 ? void 0 : _a.toLowerCase();
                    for (_i = 0, _b = nodeStore.values(); _i < _b.length; _i++) {
                        node = _b[_i];
                        if (matchingNodes.length >= maxNodes)
                            break;
                        matches = true;
                        if (query.entityType && node.type !== query.entityType)
                            matches = false;
                        if (query.app && node.app !== query.app)
                            matches = false;
                        if (keyword) {
                            searchText = "".concat(node.label, " ").concat(node.entityId, " ").concat(JSON.stringify(node.properties)).toLowerCase();
                            if (!searchText.includes(keyword))
                                matches = false;
                        }
                        if (matches)
                            matchingNodes.push(node);
                    }
                    nodeIds = new Set(matchingNodes.map(function (n) { return n.id; }));
                    matchingEdges = [];
                    for (_c = 0, _d = edgeStore.values(); _c < _d.length; _c++) {
                        edge = _d[_c];
                        if (nodeIds.has(edge.source) && nodeIds.has(edge.target)) {
                            matchingEdges.push(edge);
                        }
                    }
                    return [2 /*return*/, {
                            nodes: matchingNodes,
                            edges: matchingEdges,
                            stats: {
                                totalNodes: matchingNodes.length,
                                totalEdges: matchingEdges.length,
                                appsTraversed: __spreadArray([], new Set(matchingNodes.map(function (n) { return n.app; })), true)
                            }
                        }];
            }
        });
    });
}
exports.searchGraph = searchGraph;
function filterResult(result, query, maxNodes) {
    var nodes = result.nodes;
    if (query.entityType)
        nodes = nodes.filter(function (n) { return n.type === query.entityType; });
    if (query.app)
        nodes = nodes.filter(function (n) { return n.app === query.app; });
    if (query.keyword) {
        var kw_1 = query.keyword.toLowerCase();
        nodes = nodes.filter(function (n) {
            return "".concat(n.label, " ").concat(n.entityId, " ").concat(JSON.stringify(n.properties)).toLowerCase().includes(kw_1);
        });
    }
    nodes = nodes.slice(0, maxNodes);
    var nodeIds = new Set(nodes.map(function (n) { return n.id; }));
    var edges = result.edges.filter(function (e) { return nodeIds.has(e.source) || nodeIds.has(e.target); });
    return {
        nodes: nodes,
        edges: edges,
        stats: {
            totalNodes: nodes.length,
            totalEdges: edges.length,
            appsTraversed: __spreadArray([], new Set(nodes.map(function (n) { return n.app; })), true)
        }
    };
}
function findPaths(fromNodeId, toNodeId) {
    // BFS to find shortest paths
    var paths = [];
    var visited = new Set();
    var queue = [{ nodeId: fromNodeId, path: [fromNodeId] }];
    var maxPaths = 5;
    var maxSearchDepth = 6;
    while (queue.length > 0 && paths.length < maxPaths) {
        var _a = queue.shift(), nodeId = _a.nodeId, path = _a.path;
        if (path.length > maxSearchDepth)
            continue;
        if (nodeId === toNodeId && path.length > 1) {
            paths.push({ from: fromNodeId, to: toNodeId, via: path.slice(1, -1) });
            continue;
        }
        if (visited.has(nodeId) && nodeId !== fromNodeId)
            continue;
        visited.add(nodeId);
        // Find neighbors
        for (var _i = 0, _b = edgeStore.values(); _i < _b.length; _i++) {
            var edge = _b[_i];
            var neighbor = null;
            if (edge.source === nodeId)
                neighbor = edge.target;
            else if (edge.target === nodeId)
                neighbor = edge.source;
            if (neighbor && !path.includes(neighbor)) {
                queue.push({ nodeId: neighbor, path: __spreadArray(__spreadArray([], path, true), [neighbor], false) });
            }
        }
    }
    return paths;
}
exports.findPaths = findPaths;
function getGraphStats() {
    var nodesByType = {};
    var nodesByApp = {};
    var edgesByRelationship = {};
    for (var _i = 0, _a = nodeStore.values(); _i < _a.length; _i++) {
        var node = _a[_i];
        nodesByType[node.type] = (nodesByType[node.type] || 0) + 1;
        nodesByApp[node.app] = (nodesByApp[node.app] || 0) + 1;
    }
    for (var _b = 0, _c = edgeStore.values(); _b < _c.length; _b++) {
        var edge = _c[_b];
        edgesByRelationship[edge.relationship] = (edgesByRelationship[edge.relationship] || 0) + 1;
    }
    return {
        nodeCount: nodeStore.size,
        edgeCount: edgeStore.size,
        nodesByType: nodesByType,
        nodesByApp: nodesByApp,
        edgesByRelationship: edgesByRelationship
    };
}
exports.getGraphStats = getGraphStats;
// Export store accessors for API endpoints
function getNode(id) {
    return nodeStore.get(id);
}
exports.getNode = getNode;
function getAllNodes() {
    return __spreadArray([], nodeStore.values(), true);
}
exports.getAllNodes = getAllNodes;
function getAllEdges() {
    return __spreadArray([], edgeStore.values(), true);
}
exports.getAllEdges = getAllEdges;
