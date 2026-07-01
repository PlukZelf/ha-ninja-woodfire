"use strict";
// Trace the ADVERT decrypt path (extProcessBTData), which fires AUTOMATICALLY from
// proximity to the grill — no taps needed. Same safe pattern that worked for
// extDecryptData earlier: single hook, Stalker call-tracing scoped to one call,
// unfollow immediately in onLeave. Caps total captured calls to stay safe.

var mod = Process.findModuleByName("libgrillcore_android.so");
if (!mod) {
    console.log("[!] libgrillcore_android.so not found");
} else {
    console.log("[*] lib @ " + mod.base);
}

var exportMap = {};
mod.enumerateExports().forEach(function (e) { if (e.type === "function") exportMap[e.name] = e.address; });

var TARGET = "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData";
var addr = exportMap[TARGET];
if (!addr) {
    console.log("[!] " + TARGET + " not found");
} else {
    console.log("[HOOK] extProcessBTData @ 0x" + addr.sub(mod.base).toString(16));

    var jni = null;
    function initJNI(env) {
        if (jni) return;
        var vt = env.readPointer();
        jni = {
            GetStringUTFChars: new NativeFunction(vt.add(169 * 8).readPointer(), 'pointer', ['pointer', 'pointer', 'pointer']),
            GetArrayLength: new NativeFunction(vt.add(171 * 8).readPointer(), 'int', ['pointer', 'pointer']),
            GetByteArrayElements: new NativeFunction(vt.add(184 * 8).readPointer(), 'pointer', ['pointer', 'pointer', 'pointer']),
            ReleaseByteArrayElements: new NativeFunction(vt.add(192 * 8).readPointer(), 'void', ['pointer', 'pointer', 'pointer', 'int']),
        };
    }
    function readJStr(env, jstr) {
        if (jstr.isNull()) return "(null)";
        initJNI(env);
        var p = jni.GetStringUTFChars(env, jstr, ptr(0));
        return p.readUtf8String();
    }
    function readJBytes(env, jarr, maxShow) {
        if (jarr.isNull()) return { hex: "(null)", len: 0 };
        initJNI(env);
        var len = jni.GetArrayLength(env, jarr);
        var buf = jni.GetByteArrayElements(env, jarr, ptr(0));
        maxShow = maxShow || 64;
        var hex = [];
        for (var i = 0; i < Math.min(len, maxShow); i++) hex.push(('0' + buf.add(i).readU8().toString(16)).slice(-2));
        jni.ReleaseByteArrayElements(env, jarr, buf, 0);
        return { hex: hex.join(' '), len: len };
    }

    var callCount = 0;
    var CAP = 5;  // only trace the first 5 advert calls, then stop tracing (still let function run normally)

    Interceptor.attach(addr, {
        onEnter: function (args) {
            callCount++;
            if (callCount > CAP) return;  // don't attach Stalker beyond the cap
            this._trace = true;
            console.log("\n=== extProcessBTData #" + callCount + " ===");
            try {
                console.log("  uuid: " + readJStr(args[0], args[2]));
                var d = readJBytes(args[0], args[3]);
                console.log("  data (" + d.len + "B): " + d.hex);
                console.log("  rssi: " + args[4].toInt32());
            } catch (e) { console.log("  (read error: " + e.message + ")"); }

            this._tid = Process.getCurrentThreadId();
            this._seen = {};
            var seen = this._seen;
            Stalker.follow(this._tid, {
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
            if (!this._trace) return;
            try {
                Stalker.unfollow(this._tid);
                Stalker.flush();
                var entries = Object.keys(this._seen).map(function (off) { return { off: off, count: this._seen[off] }; }, this);
                entries.sort(function (a, b) { return b.count - a.count; });
                console.log("  [top called offsets]: " + entries.slice(0, 20).map(function (e) {
                    return "0x" + e.off + "x" + e.count;
                }).join(", "));
            } catch (e) {
                console.log("  [stalker error: " + e.message + "]");
            }
            if (callCount >= CAP) {
                console.log("\n[*] Cap of " + CAP + " calls reached — tracing stopped (function still runs normally).");
            }
        }
    });
}

console.log("\n[*] Ready. Adverts should fire automatically within a few seconds near the grill.");
