"use strict";
exports.__esModule = true;
var temporalAdmin_1 = require("~/server/utils/temporalAdmin");
exports["default"] = defineEventHandler(function () {
    var limit = 50;
    return {
        history: (0, temporalAdmin_1.getActionHistory)(limit),
        undoable: (0, temporalAdmin_1.getUndoableActions)()
    };
});
