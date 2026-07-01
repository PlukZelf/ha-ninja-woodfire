"use strict";
// Runs inside the app process (Frida gadget = app UID) → reads app private storage
// to find the PERSISTED session key. No Java bridge (unreliable in this gadget);
// uses libc opendir/readdir + Frida's File API. No app restart / no user taps.

var PKG = "com.sharkninja.ninja.connected.kitchen";
var BASE = "/data/data/" + PKG;

// Resolve libc symbols via export map (Module.getExportByName is not available here).
var libc = Process.findModuleByName("libc.so");
var cexp = {};
libc.enumerateExports().forEach(function (e) { if (e.type === "function") cexp[e.name] = e.address; });

var opendir  = new NativeFunction(cexp["opendir"],  "pointer", ["pointer"]);
var readdir  = new NativeFunction(cexp["readdir"],  "pointer", ["pointer"]);
var closedir = new NativeFunction(cexp["closedir"], "int",     ["pointer"]);

function listDir(path) {
    var out = [];
    var dp = opendir(Memory.allocUtf8String(path));
    if (dp.isNull()) return null;
    var ent;
    while (!(ent = readdir(dp)).isNull()) {
        // bionic struct dirent64: d_ino(8) d_off(8) d_reclen(2) d_type(1) d_name[]
        var type = ent.add(18).readU8();
        var name = ent.add(19).readUtf8String();
        if (name !== "." && name !== "..") out.push({ name: name, type: type });
    }
    closedir(dp);
    return out;  // type 4 = DT_DIR, 8 = DT_REG
}

function readFile(path, maxN) {
    try {
        var f = new File(path, "rb");
        var data = f.readBytes(maxN || 262144);
        f.close();
        return data;  // ArrayBuffer
    } catch (e) {
        return null;
    }
}

function u8(ab) { return new Uint8Array(ab); }

function toText(ab, n) {
    var a = u8(ab); var len = Math.min(a.length, n || a.length); var s = "";
    for (var i = 0; i < len; i++) { var c = a[i]; s += (c >= 0x20 && c < 0x7f) ? String.fromCharCode(c) : "."; }
    return s;
}
function toHex(ab, n) {
    var a = u8(ab); var len = Math.min(a.length, n || a.length); var h = [];
    for (var i = 0; i < len; i++) h.push(('0' + a[i].toString(16)).slice(-2));
    return h.join(' ');
}

console.log("\n========== APP STORAGE DUMP ==========");
console.log("[*] base: " + BASE);

var top = listDir(BASE);
if (!top) {
    console.log("[!] cannot open " + BASE + " — wrong UID?");
} else {
    console.log("[*] top-level:");
    top.forEach(function (e) { console.log("    " + (e.type === 4 ? "d" : "-") + " " + e.name); });
}

// Full dump of every shared_prefs XML (keys/tokens usually live here)
console.log("\n========== shared_prefs CONTENTS ==========");
var prefs = listDir(BASE + "/shared_prefs") || [];
prefs.forEach(function (e) {
    var full = BASE + "/shared_prefs/" + e.name;
    var data = readFile(full, 262144);
    console.log("\n--- " + e.name + " ---");
    console.log(data ? toText(data) : "(unreadable)");
});

// Previews for files / databases / no_backup (+ one level of subdirs)
console.log("\n========== files / databases / no_backup ==========");
["files", "databases", "no_backup", "app_flutter"].forEach(function (sub) {
    var dir = BASE + "/" + sub;
    var entries = listDir(dir);
    if (!entries) return;
    console.log("\n[" + sub + "] " + entries.length + " entries:");
    entries.forEach(function (e) {
        var full = dir + "/" + e.name;
        console.log("  " + (e.type === 4 ? "d" : "-") + " " + e.name);
        if (e.type === 4) {
            var subEntries = listDir(full) || [];
            subEntries.forEach(function (se) {
                console.log("      " + (se.type === 4 ? "d" : "-") + " " + se.name);
                if (se.type !== 4) {
                    var d = readFile(full + "/" + se.name, 2048);
                    if (d) {
                        console.log("        hex: " + toHex(d, 96));
                        console.log("        txt: " + toText(d, 160));
                    }
                }
            });
        } else {
            var d = readFile(full, 2048);
            if (d) {
                console.log("      hex: " + toHex(d, 96));
                console.log("      txt: " + toText(d, 160));
            }
        }
    });
});

console.log("\n========== END STORAGE DUMP ==========");
