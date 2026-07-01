"use strict";
// Deep-dump the GrillCore SDK per-grill storage + MMKV store to locate the BT session key.

var BASE = "/data/data/com.sharkninja.ninja.connected.kitchen";

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
        var type = ent.add(18).readU8();
        var name = ent.add(19).readUtf8String();
        if (name !== "." && name !== "..") out.push({ name: name, type: type });
    }
    closedir(dp);
    return out;
}
function readFile(path, maxN) {
    try { var f = new File(path, "rb"); var d = f.readBytes(maxN || 1048576); f.close(); return d; }
    catch (e) { return null; }
}
function u8(ab){ return new Uint8Array(ab); }
function toText(ab, n){ var a=u8(ab),len=Math.min(a.length,n||a.length),s="";for(var i=0;i<len;i++){var c=a[i];s+=(c>=0x20&&c<0x7f)?String.fromCharCode(c):".";}return s; }
function toHex(ab, n){ var a=u8(ab),len=Math.min(a.length,n||a.length),h=[];for(var i=0;i<len;i++)h.push(('0'+a[i].toString(16)).slice(-2));return h.join(' '); }

// Recursive walk with full dump
function walk(path, depth) {
    var pad = "  ".repeat(depth);
    var entries = listDir(path);
    if (!entries) { return; }
    entries.forEach(function (e) {
        var full = path + "/" + e.name;
        if (e.type === 4) {
            console.log(pad + "d " + e.name + "/");
            walk(full, depth + 1);
        } else {
            var d = readFile(full, 65536);
            var sz = d ? d.byteLength : 0;
            console.log(pad + "- " + e.name + " (" + sz + " bytes)");
            if (d && sz > 0) {
                console.log(pad + "    hex: " + toHex(d, 256));
                console.log(pad + "    txt: " + toText(d, 300));
            }
        }
    });
}

console.log("\n===== cloudcore FULL WALK =====");
walk(BASE + "/files/cloudcore", 0);

console.log("\n===== mmkv FULL DUMP =====");
["sn_storage", "sn_storage.crc"].forEach(function (name) {
    var full = BASE + "/files/mmkv/" + name;
    var d = readFile(full, 262144);
    console.log("\n--- mmkv/" + name + " (" + (d ? d.byteLength : 0) + " bytes) ---");
    if (d) {
        console.log("hex:\n" + toHex(d, 2048));
        console.log("txt:\n" + toText(d, 2048));
    }
});

console.log("\n===== app_json =====");
walk(BASE + "/app_json", 0);

console.log("\n===== END =====");
