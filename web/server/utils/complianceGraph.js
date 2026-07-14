"use strict";
/**
 * Compliance Graph — maps cross-app dependencies for regulatory actions.
 * When a compliance event fires in one app, the graph traces the impact
 * across the fleet and suggests/executes cascading responses.
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
exports.getImpactHistory = exports.addEdge = exports.getGraph = exports.analyzeImpact = exports.traceEntity = void 0;
// Default edges — hardcoded knowledge of cross-app relationships
var edges = [
    // User identity flows
    { source: { app: 'apparently', entity: 'user' }, target: { app: 'smarter', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
    { source: { app: 'apparently', entity: 'user' }, target: { app: 'tomorrow', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
    { source: { app: 'apparently', entity: 'user' }, target: { app: 'galop', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
    { source: { app: 'apparently', entity: 'user' }, target: { app: 'hisanta', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
    // Compliance state flows
    { source: { app: 'apparently', entity: 'document' }, target: { app: 'tomorrow', entity: 'transaction' }, relationship: 'depends_on', propagation: 'manual' },
    { source: { app: 'apparently', entity: 'document' }, target: { app: 'smarter', entity: 'document' }, relationship: 'mirrors', propagation: 'auto' },
    { source: { app: 'galop', entity: 'user' }, target: { app: 'hisanta', entity: 'user' }, relationship: 'references', propagation: 'auto' },
    { source: { app: 'tomorrow', entity: 'transaction' }, target: { app: 'pareto', entity: 'feature' }, relationship: 'depends_on', propagation: 'manual' },
    { source: { app: 'smarter', entity: 'user' }, target: { app: 'orchestrator', entity: 'user' }, relationship: 'references', propagation: 'auto' },
    { source: { app: 'pareto', entity: 'user' }, target: { app: 'galop', entity: 'user' }, relationship: 'mirrors', propagation: 'auto' },
];
// In-memory node registry (populated from edges + impact analyses)
var nodeRegistry = new Map();
// Initialize nodes from edges
function ensureNodesFromEdges() {
    for (var _i = 0, edges_1 = edges; _i < edges_1.length; _i++) {
        var edge = edges_1[_i];
        var sourceKey = "".concat(edge.source.app, ":").concat(edge.source.entity);
        var targetKey = "".concat(edge.target.app, ":").concat(edge.target.entity);
        if (!nodeRegistry.has(sourceKey)) {
            nodeRegistry.set(sourceKey, { app: edge.source.app, entity: edge.source.entity, status: 'clean' });
        }
        if (!nodeRegistry.has(targetKey)) {
            nodeRegistry.set(targetKey, { app: edge.target.app, entity: edge.target.entity, status: 'clean' });
        }
    }
}
// Ensure initialization
ensureNodesFromEdges();
// Impact analysis history
var impactHistory = [];
// Compliance action mappings
var ACTION_MAP = {
    'user:flagged': { action: 'flag_user', reason: 'User flagged in source app — mirror flag across fleet' },
    'user:suspended': { action: 'suspend_user', reason: 'User suspended — propagate suspension to dependent apps' },
    'user:blocked': { action: 'block_user', reason: 'User blocked — enforce block across all mirrored apps' },
    'document:flagged': { action: 'review_document', reason: 'Document flagged — review dependent transactions and mirrors' },
    'document:suspended': { action: 'freeze_document', reason: 'Document suspended — freeze downstream transactions' },
    'transaction:flagged': { action: 'hold_transaction', reason: 'Transaction flagged — hold and review dependent features' },
    'transaction:suspended': { action: 'freeze_transaction', reason: 'Transaction suspended — block dependent features' },
    'feature:flagged': { action: 'disable_feature', reason: 'Feature flagged — evaluate impact on users' },
    'feature:blocked': { action: 'kill_feature', reason: 'Feature blocked — disable across fleet' }
};
/**
 * Trace all nodes reachable from a given app+entity via edges (BFS).
 */
function traceEntity(app, entityType, entityId) {
    var startKey = "".concat(app, ":").concat(entityType);
    var visited = new Set([startKey]);
    var queue = [startKey];
    var result = [];
    while (queue.length > 0) {
        var current = queue.shift();
        var _a = current.split(':'), currentApp = _a[0], currentEntity = _a[1];
        for (var _i = 0, edges_2 = edges; _i < edges_2.length; _i++) {
            var edge = edges_2[_i];
            var edgeSourceKey = "".concat(edge.source.app, ":").concat(edge.source.entity);
            var edgeTargetKey = "".concat(edge.target.app, ":").concat(edge.target.entity);
            if (edgeSourceKey === current && !visited.has(edgeTargetKey)) {
                visited.add(edgeTargetKey);
                queue.push(edgeTargetKey);
                var node = nodeRegistry.get(edgeTargetKey) || { app: edge.target.app, entity: edge.target.entity, status: 'clean' };
                result.push(__assign(__assign({}, node), { entityId: entityId }));
            }
        }
    }
    return result;
}
exports.traceEntity = traceEntity;
/**
 * Analyze the impact of a compliance action on a given app/entity.
 */
function analyzeImpact(triggerApp, triggerAction, entityType, entityId) {
    var affectedNodes = traceEntity(triggerApp, entityType, entityId);
    // Generate suggested actions based on the trigger and relationships
    var suggestedActions = [];
    var _loop_1 = function (node) {
        var actionKey = "".concat(node.entity, ":").concat(triggerAction);
        var mapping = ACTION_MAP[actionKey] || { action: "review_".concat(node.entity), reason: "Cascading review needed due to ".concat(triggerAction, " in ").concat(triggerApp) };
        // Find the edge to determine if propagation is auto
        var edge = edges.find(function (e) {
            return e.target.app === node.app && e.target.entity === node.entity;
        });
        suggestedActions.push({
            app: node.app,
            action: mapping.action,
            reason: mapping.reason,
            auto: (edge === null || edge === void 0 ? void 0 : edge.propagation) === 'auto'
        });
    };
    for (var _i = 0, affectedNodes_1 = affectedNodes; _i < affectedNodes_1.length; _i++) {
        var node = affectedNodes_1[_i];
        _loop_1(node);
    }
    var analysis = {
        triggerApp: triggerApp,
        triggerAction: triggerAction,
        affectedNodes: affectedNodes,
        suggestedActions: suggestedActions,
        timestamp: new Date().toISOString()
    };
    // Store in history
    impactHistory.unshift(analysis);
    if (impactHistory.length > 50)
        impactHistory.pop();
    return analysis;
}
exports.analyzeImpact = analyzeImpact;
/**
 * Return the full compliance graph.
 */
function getGraph() {
    ensureNodesFromEdges();
    return {
        nodes: Array.from(nodeRegistry.values()),
        edges: __spreadArray([], edges, true)
    };
}
exports.getGraph = getGraph;
/**
 * Add a new edge to the graph.
 */
function addEdge(edge) {
    edges.push(edge);
    ensureNodesFromEdges();
}
exports.addEdge = addEdge;
/**
 * Get impact analysis history.
 */
function getImpactHistory() {
    return impactHistory;
}
exports.getImpactHistory = getImpactHistory;
