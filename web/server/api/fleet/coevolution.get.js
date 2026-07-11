"use strict";
exports.__esModule = true;
// GET /api/fleet/coevolution — run the adversary↔defender loop to a fixed point and report
// the hardened safe-autonomy envelope (the largest autonomy that survives adversarial probing).
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
exports["default"] = defineEventHandler(function () {
    var result = (0, fleetAdmin_1.coEvolve)();
    return { rounds: result.rounds, tightenings: result.tightenings, residualHarm: result.residualHarm, safe: result.residualHarm < 0.3 };
});
