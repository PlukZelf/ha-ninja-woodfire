"use strict";
// Pull full sn_storage + .crc as base64 (offline artifacts) and recon MMKV loading.
// Attach to running app; no restart / no taps.

var BASE = "/data/data/com.sharkninja.ninja.connected.kitchen";

function readFileFull(path) {
    try {
        var f = new File(path, "rb");
        var d = f.readBytes(1048576);
        f.close();
        return d;
    } catch (e) { return null; }
}
function b64(ab) {
    // Frida has a global base64 via Java? Use manual.
    var bytes = new Uint8Array(ab);
    var chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    var out = "";
    for (var i = 0; i < bytes.length; i += 3) {
        var b0 = bytes[i], b1 = i+1 < bytes.length ? bytes[i+1] : 0, b2 = i+2 < bytes.length ? bytes[i+2] : 0;
        out += chars[b0 >> 2];
        out += chars[((b0 & 3) << 4) | (b1 >> 4)];
        out += (i+1 < bytes.length) ? chars[((b1 & 15) << 2) | (b2 >> 6)] : "=";
        out += (i+2 < bytes.length) ? chars[b2 & 63] : "=";
    }
    return out;
}

["sn_storage", "sn_storage.crc"].forEach(function (name) {
    var d = readFileFull(BASE + "/files/mmkv/" + name);
    if (d) {
        console.log("###B64### " + name + " " + d.byteLength);
        console.log(b64(d));
        console.log("###END### " + name);
    } else {
        console.log("[!] cannot read " + name);
    }
});

// Recon: which modules relate to mmkv / crypto?
console.log("\n===== modules (mmkv / crypto / storage) =====");
Process.enumerateModules().forEach(function (m) {
    var n = m.name.toLowerCase();
    if (n.indexOf("mmkv") !== -1 || n.indexOf("crypt") !== -1 || n.indexOf("sqlcipher") !== -1) {
        console.log("  " + m.name + " @ " + m.base + " (" + m.size + ")");
    }
});

// If a libmmkv exists, show its exported functions that take a crypt key.
var mmkv = null;
Process.enumerateModules().forEach(function (m) {
    if (m.name.toLowerCase().indexOf("mmkv") !== -1) mmkv = m;
});
if (mmkv) {
    console.log("\n===== " + mmkv.name + " exports (getMMKV / crypt / init) =====");
    mmkv.enumerateExports().forEach(function (e) {
        var n = e.name.toLowerCase();
        if (n.indexOf("mmkv") !== -1 || n.indexOf("crypt") !== -1 || n.indexOf("init") !== -1 || n.indexOf("withid") !== -1) {
            console.log("  " + e.name);
        }
    });
} else {
    console.log("\n[*] No separate libmmkv module — MMKV may be statically linked into libgrillcore or an RN lib.");
    console.log("[*] Searching all modules for 'MMKV' symbol names...");
    Process.enumerateModules().forEach(function (m) {
        try {
            var hits = m.enumerateExports().filter(function (e) {
                return e.name.indexOf("MMKV") !== -1 || e.name.indexOf("getMMKV") !== -1;
            });
            if (hits.length) {
                console.log("  [" + m.name + "]");
                hits.slice(0, 10).forEach(function (e) { console.log("    " + e.name); });
            }
        } catch (e) {}
    });
}

console.log("\n===== DONE =====");
