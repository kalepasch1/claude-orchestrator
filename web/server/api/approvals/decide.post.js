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
var fleetSupabase_1 = require("../../utils/fleetSupabase");
exports["default"] = defineEventHandler(function (event) { return __awaiter(void 0, void 0, void 0, function () {
    var body, id, status, approver, sb, _a, card, readError, now, patch, _b, data, error;
    return __generator(this, function (_c) {
        switch (_c.label) {
            case 0: return [4 /*yield*/, readBody(event)];
            case 1:
                body = _c.sent();
                id = body === null || body === void 0 ? void 0 : body.id;
                status = body === null || body === void 0 ? void 0 : body.status;
                approver = String((body === null || body === void 0 ? void 0 : body.approver) || 'dashboard').trim() || 'dashboard';
                if (!id || !['approved', 'denied'].includes(String(status))) {
                    throw createError({ statusCode: 400, message: 'id and approved/denied status are required' });
                }
                sb = (0, fleetSupabase_1.serviceClient)();
                return [4 /*yield*/, sb
                        .from('approvals')
                        .select('*')
                        .eq('id', id)
                        .maybeSingle()];
            case 2:
                _a = _c.sent(), card = _a.data, readError = _a.error;
                if (readError)
                    throw createError({ statusCode: 500, message: readError.message });
                if (!card)
                    throw createError({ statusCode: 404, message: 'approval not found' });
                now = new Date().toISOString();
                if (status === 'approved' && Number(card.approvals_required || 1) >= 2) {
                    if (!card.decided_by) {
                        patch = { decided_by: approver };
                    }
                    else if (card.decided_by === approver) {
                        throw createError({ statusCode: 409, message: 'a different approver is required for the second approval' });
                    }
                    else {
                        patch = { status: 'approved', second_approver: approver, decided_at: now };
                    }
                }
                else {
                    patch = { status: status, decided_at: now, decided_by: approver };
                }
                return [4 /*yield*/, sb
                        .from('approvals')
                        .update(patch)
                        .eq('id', id)
                        .select('*')
                        .maybeSingle()];
            case 3:
                _b = _c.sent(), data = _b.data, error = _b.error;
                if (error)
                    throw createError({ statusCode: 500, message: error.message });
                return [2 /*return*/, { ok: true, approval: data }];
        }
    });
}); });
