"use strict";
exports.__esModule = true;
// GET /api/fleet/constitution-verify — machine-checks the locked-dimension invariants across a
// bounded action space (money never auto-allows, identity/termination never auto, prod-data +
// secret rotation never auto). Returns any breach. Run this as a gate before shipping an amendment.
var fleetAdmin_1 = require("@darwin/kernel/fleetAdmin");
exports["default"] = defineEventHandler(function () { return (0, fleetAdmin_1.verifyConstitutionInvariants)(); });
