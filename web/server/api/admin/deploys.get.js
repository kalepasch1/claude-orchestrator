"use strict";
exports.__esModule = true;
var canaryDeploy_1 = require("~/server/utils/canaryDeploy");
exports["default"] = defineEventHandler(function () {
    return { deploys: (0, canaryDeploy_1.getDeployHistory)() };
});
