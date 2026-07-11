"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
exports.__esModule = true;
exports.planeChainFor = exports.handleDecision = exports.ingestEvent = exports.governAndRoute = void 0;
/**
 * Fleet Admin Control Plane — the orchestration loop now lives in the kernel
 * (zero-dep + unit-tested). This module just re-exports it so the Nitro endpoints
 * have a stable local import, and `fleetSupabase.ts` supplies the Supabase/fetch
 * ports it runs on.
 */
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
__createBinding(exports, fleetAdmin_1, "governAndRoute");
__createBinding(exports, fleetAdmin_1, "ingestEvent");
__createBinding(exports, fleetAdmin_1, "handleDecision");
__createBinding(exports, fleetAdmin_1, "planeChainFor");
