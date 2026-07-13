"use strict";
exports.__esModule = true;
var appClients_1 = require("../../utils/appClients");
exports["default"] = defineEventHandler(function () {
    return { apps: (0, appClients_1.listApps)() };
});
