"use strict";
exports.__esModule = true;
// GET /api/fleet/capabilities — the plane published as Darwin capabilities. Any orchestrator
// (this portfolio or a future one) discovers these and instantiates governed admin autonomy
// in one line, pointing at this deployment's /api/fleet/* endpoints.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
exports["default"] = defineEventHandler(function () {
    var _a;
    var baseUrl = (_a = process.env.ORCHESTRATOR_BASE_URL) !== null && _a !== void 0 ? _a : '';
    return { capabilities: (0, fleetAdmin_1.fleetAdminCapabilities)(baseUrl), governCapabilityId: (0, fleetAdmin_1.fleetGovernCapabilityId)(baseUrl) };
});
