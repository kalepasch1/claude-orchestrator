"use strict";
exports.__esModule = true;
exports.serialize = exports.parse = void 0;
function parse(input) {
    if (input === void 0) { input = ''; }
    var out = {};
    for (var _i = 0, _a = input.split(';'); _i < _a.length; _i++) {
        var part = _a[_i];
        var trimmed = part.trim();
        if (!trimmed)
            continue;
        var eq = trimmed.indexOf('=');
        if (eq < 0)
            continue;
        var key = trimmed.slice(0, eq).trim();
        var raw = trimmed.slice(eq + 1).trim();
        if (!key)
            continue;
        try {
            out[key] = decodeURIComponent(raw);
        }
        catch (_b) {
            out[key] = raw;
        }
    }
    return out;
}
exports.parse = parse;
function serialize(name, value, options) {
    if (options === void 0) { options = {}; }
    var parts = ["".concat(name, "=").concat(encodeURIComponent(value))];
    if (options.maxAge != null)
        parts.push("Max-Age=".concat(Math.floor(options.maxAge)));
    if (options.domain)
        parts.push("Domain=".concat(options.domain));
    if (options.path)
        parts.push("Path=".concat(options.path));
    if (options.expires)
        parts.push("Expires=".concat(options.expires.toUTCString()));
    if (options.httpOnly)
        parts.push('HttpOnly');
    if (options.secure)
        parts.push('Secure');
    if (options.sameSite) {
        var sameSite = options.sameSite === true ? 'Strict' : String(options.sameSite);
        parts.push("SameSite=".concat(sameSite.charAt(0).toUpperCase()).concat(sameSite.slice(1).toLowerCase()));
    }
    return parts.join('; ');
}
exports.serialize = serialize;
