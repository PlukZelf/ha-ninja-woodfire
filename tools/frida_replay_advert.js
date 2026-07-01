"use strict";
// Pure-native replay: no Java bridge (unavailable in this Gadget build).
// 1. Hook extDecryptData (fires automatically every few seconds while GATT-connected)
//    to harvest a live, valid JNIEnv* + the real BTManager$Companion jobject.
// 2. Use that env's raw JNI vtable to build a jstring + jbyteArray for our captured advert.
// 3. Call extProcessBTData(env, companion, uuid, data, rssi) ourselves — deterministic,
//    no waiting on real BLE advert events.

var UUID = "AA:BB:CC:DD:EE:FF";
var ADVERT_HEX =
    "02 01 06 03 03 bb fc 17 ff 4f 0c 26 48 79 66 1a a1 be 8b e9 5f eb 9a 16 e1 4d 4c b3 46 85 49 " +
    "03 19 00 00 1a ff 4f 0c 17 38 61 30 d5 30 71 87 74 32 9d 07 c4 87 43 3a 99 27 d9 1e e9 5e 1b";
var RSSI = -85;

function hexToBytes(hex) {
    var parts = hex.trim().split(/\s+/);
    return parts.map(function (p) { var v = parseInt(p, 16); return v > 127 ? v - 256 : v; });
}

var mod = Process.findModuleByName("libgrillcore_android.so");
console.log("[*] lib @ " + mod.base);
var exportMap = {};
mod.enumerateExports().forEach(function (e) { if (e.type === "function") exportMap[e.name] = e.address; });

var pDecrypt = exportMap["Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData"];
var pProcessBT = exportMap["Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData"];
console.log("[HOOK] extDecryptData @ 0x" + pDecrypt.sub(mod.base).toString(16) + " (harvesting env)");
console.log("[*] extProcessBTData @ 0x" + pProcessBT.sub(mod.base).toString(16));

var harvested = false;

function doReplay(env, companion) {
    console.log("\n[*] Harvested env=" + env + " companion=" + companion);
    console.log("[*] Replaying captured advert...");

    var vt = env.readPointer();
    function jfn(idx, retType, argTypes) {
        return new NativeFunction(vt.add(idx * 8).readPointer(), retType, argTypes);
    }
    var NewStringUTF = jfn(167, "pointer", ["pointer", "pointer"]);
    var NewByteArray = jfn(176, "pointer", ["pointer", "int"]);
    var SetByteArrayRegion = jfn(196, "void", ["pointer", "pointer", "int", "int", "pointer"]);

    var bytes = hexToBytes(ADVERT_HEX);
    var uuidCStr = Memory.allocUtf8String(UUID);
    var jstr = NewStringUTF(env, uuidCStr);

    var jarr = NewByteArray(env, bytes.length);
    var nativeBuf = Memory.alloc(bytes.length);
    for (var i = 0; i < bytes.length; i++) nativeBuf.add(i).writeS8(bytes[i]);
    SetByteArrayRegion(env, jarr, 0, bytes.length, nativeBuf);

    console.log("[*] built jstring=" + jstr + " jarr=" + jarr + " (" + bytes.length + " bytes)");

    // Stalker-trace the synthetic call.
    var tid = Process.getCurrentThreadId();
    var seen = {};
    var traceHandle = Interceptor.attach(pProcessBT, {
        onEnter: function (args) {
            console.log("[*] extProcessBTData ENTER (synthetic)");
            Stalker.follow(tid, {
                events: { call: true },
                onReceive: function (events) {
                    var calls = Stalker.parse(events, { annotate: true, stringify: false });
                    calls.forEach(function (c) {
                        var target = c.target !== undefined ? c.target : (Array.isArray(c) ? c[2] : null);
                        var type = c.type !== undefined ? c.type : (Array.isArray(c) ? c[0] : null);
                        if (type !== 'call' || !target) return;
                        if (target.compare(mod.base) >= 0 && target.compare(mod.base.add(mod.size)) < 0) {
                            var off = target.sub(mod.base).toString(16);
                            seen[off] = (seen[off] || 0) + 1;
                        }
                    });
                }
            });
        },
        onLeave: function (retval) {
            try { Stalker.unfollow(tid); Stalker.flush(); } catch (e) { console.log("[!] stalker: " + e.message); }
            var entries = Object.keys(seen).map(function (off) { return { off: off, count: seen[off] }; });
            entries.sort(function (a, b) { return b.count - a.count; });
            console.log("[*] extProcessBTData LEAVE");
            console.log("[top called offsets]: " + entries.slice(0, 30).map(function (e) {
                return "0x" + e.off + "x" + e.count;
            }).join(", "));
            traceHandle.detach();
        }
    });

    var fn = new NativeFunction(pProcessBT, "void", ["pointer", "pointer", "pointer", "pointer", "int"]);
    fn(env, companion, jstr, jarr, RSSI);
    console.log("\n[*] Synthetic replay call returned.");
}

Interceptor.attach(pDecrypt, {
    onEnter: function (args) {
        if (harvested) return;
        harvested = true;
        console.log("\n[*] extDecryptData fired naturally -> harvesting env/companion");
        this._env = args[0];
        this._companion = args[1];
    },
    onLeave: function (retval) {
        // Do the replay AFTER the real call fully completes (avoid reentrant-lock deadlock).
        if (this._env) doReplay(this._env, this._companion);
    }
});

console.log("\n[*] Waiting for a natural extDecryptData call (should be automatic, every few sec while connected)...");
