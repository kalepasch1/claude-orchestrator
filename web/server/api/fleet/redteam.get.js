"use strict";
exports.__esModule = true;
// GET /api/fleet/redteam — adversarial autonomy sweep: probe every domain ceiling with
// synthetic edge cases and report any that would auto-run with real harm potential (gaps).
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
exports["default"] = defineEventHandler(function () {
    var _a = (0, fleetAdmin_1.runRedTeam)(), findings = _a.findings, gaps = _a.gaps;
    return { gaps: gaps, gapCount: gaps.length, probesRun: findings.length, clean: gaps.length === 0 };
});
