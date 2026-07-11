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
// GET /api/fleet/marketplace — this org's PUBLISHABLE governance artifacts, signed + ready to
// list on the shared market: its current constitution and a DP-anonymized precedent pack. Other
// orgs discover + install these so a new company inherits mature policy on day one.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
var fleetSupabase_1 = require("../../utils/fleetSupabase");
var fleetReads_1 = require("../../utils/fleetReads");
exports["default"] = defineEventHandler(function () { return __awaiter(void 0, void 0, void 0, function () {
    var sb, constitution, precedent, _a, listings;
    return __generator(this, function (_b) {
        switch (_b.label) {
            case 0:
                sb = (0, fleetSupabase_1.serviceClient)();
                constitution = (0, fleetAdmin_1.fleetAdminConstitution)();
                _a = fleetAdmin_1.buildFederatedPrecedent;
                return [4 /*yield*/, (0, fleetReads_1.appTypeStats)(sb)];
            case 1:
                precedent = _a.apply(void 0, [_b.sent()]);
                listings = [
                    (0, fleetAdmin_1.signListing)({
                        id: 'fleet-constitution-v' + constitution.version, kind: 'constitution', title: 'Fleet Admin Constitution', owner: 'this-org', version: String(constitution.version),
                        tags: ['admin', 'governance', 'billing', 'infra', 'users_access', 'trust_safety'],
                        payload: { alwaysEscalate: constitution.alwaysEscalate, rules: constitution.rules.map(function (r) { return ({ id: r.id, text: r.text, effect: r.effect, appliesTo: r.appliesTo }); }) },
                        publishedAt: new Date().toISOString()
                    }),
                    (0, fleetAdmin_1.signListing)({
                        id: 'fleet-precedent-pack', kind: 'precedent_pack', title: 'Admin precedent pack (DP-anonymized)', owner: 'this-org', version: '1.0.0',
                        tags: ['admin', 'precedent', 'autonomy'], payload: { precedent: precedent }, publishedAt: new Date().toISOString()
                    }),
                ];
                return [2 /*return*/, { listings: listings, allVerify: listings.every(fleetAdmin_1.verifyListing) }];
        }
    });
}); });
