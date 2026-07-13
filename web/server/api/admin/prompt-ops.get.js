"use strict";
exports.__esModule = true;
var promptOps_1 = require("~/server/utils/promptOps");
exports["default"] = defineEventHandler(function () {
    return { ops: (0, promptOps_1.listPromptOps)() };
});
