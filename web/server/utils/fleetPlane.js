"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.planeChainFor = exports.handleDecision = exports.ingestEvent = exports.governAndRoute = void 0;
/**
 * Fleet Admin Control Plane — the orchestration loop now lives in the kernel
 * (zero-dep + unit-tested). This module just re-exports it so the Nitro endpoints
 * have a stable local import, and `fleetSupabase.ts` supplies the Supabase/fetch
 * ports it runs on.
 */
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
Object.defineProperty(exports, "governAndRoute", { enumerable: true, get: function () { return fleetAdmin_1.governAndRoute; } });
Object.defineProperty(exports, "ingestEvent", { enumerable: true, get: function () { return fleetAdmin_1.ingestEvent; } });
Object.defineProperty(exports, "handleDecision", { enumerable: true, get: function () { return fleetAdmin_1.handleDecision; } });
Object.defineProperty(exports, "planeChainFor", { enumerable: true, get: function () { return fleetAdmin_1.planeChainFor; } });
