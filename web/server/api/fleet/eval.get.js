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
// GET /api/fleet/eval — scores the plane against a held-out slice of the resolved-decision log:
// the GATE's auto-vs-human calls (false auto-runs are the safety-critical metric) and the learned
// decision model. Run this before trusting a promotion — precision/recall on real labels.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
var fleetSupabase_1 = require("../../utils/fleetSupabase");
var fleetReads_1 = require("../../utils/fleetReads");
exports["default"] = defineEventHandler(function () { return __awaiter(void 0, void 0, void 0, function () {
    var sb, cases, _a, train, test, model, modelScore, constitution, gateCases, gateScore;
    return __generator(this, function (_b) {
        switch (_b.label) {
            case 0:
                sb = (0, fleetSupabase_1.serviceClient)();
                return [4 /*yield*/, (0, fleetReads_1.resolvedHistory)(sb)];
            case 1:
                cases = _b.sent();
                if (cases.length < 20)
                    return [2 /*return*/, { ok: false, reason: 'insufficient_labeled_history', have: cases.length }];
                _a = (0, fleetAdmin_1.splitHoldout)(cases, 5), train = _a.train, test = _a.test;
                model = (0, fleetAdmin_1.trainDecisionModel)((0, fleetAdmin_1.samplesFromResolved)(train));
                modelScore = (0, fleetAdmin_1.evalDecisionModel)(model, test);
                constitution = (0, fleetAdmin_1.fleetAdminConstitution)();
                gateCases = test.map(function (c) {
                    var action = { id: 'eval', product: 'orchestrator', domain: c.domain, type: c.type, actor: 'eval', confidence: 0.95, reversibility: c.reversibility, blastRadius: c.blastRadius, intent: 'eval', amountUsd: c.amountUsd, at: c.at };
                    var v = (0, fleetAdmin_1.governFleetAction)({ action: action, constitution: constitution });
                    return { tier: v.tier, decisionAllow: v.decision === 'allow', outcome: c.outcome };
                });
                gateScore = (0, fleetAdmin_1.evalGate)(gateCases);
                return [2 /*return*/, { ok: true, trainSize: train.length, testSize: test.length, gate: gateScore, decisionModel: modelScore }];
        }
    });
}); });
