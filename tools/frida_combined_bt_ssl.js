"use strict";

var AES_ARMED = false;
var AES_HITS_THIS_CALL = 0;

var mod = Process.findModuleByName("libgrillcore_android.so");
if (!mod) {
    console.log("[!] libgrillcore_android.so not found");
} else {
    console.log("[*] lib @ " + mod.base);
}

// Build export map
var exportMap = {};
mod.enumerateExports().forEach(function(e) {
    if (e.type === "function") exportMap[e.name] = e.address;
});

var hooks = {
    "extProcessBTData":             "Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData",
    "extDecryptData":               "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData",
    "extDecryptDataWithOptionalKey": "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptDataWithOptionalKey",
    "extEncryptData":               "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptData",
    "extEncryptDataWithOptionalKey": "Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptDataWithOptionalKey",
    "extSendBTPayload":             "Java_com_sharkninja_grillcore_BTManager_00024Companion_extSendBTPayload",
    "extSetBTAvailable":            "Java_com_sharkninja_grillcore_BTManager_00024Companion_extSetBTAvailable",
    "extSetRequestCallback":        "Java_com_sharkninja_grillcore_BTManager_00024Companion_extSetRequestCallback",
    "extGetMac":                    "Java_com_sharkninja_grillcore_BTManager_00024Companion_extGetMac",
    "extGetJoinableGrills":         "Java_com_sharkninja_grillcore_BTManager_00024Companion_extGetJoinableGrills",
    "init":                         "Java_com_sharkninja_grillcore_GrillCoreSDK_00024Companion_init",
    "extSetStateCallback":          "Java_com_sharkninja_grillcore_GrillManager_00024Companion_extSetStateCallback",
    "extSetGrillsCallback":         "Java_com_sharkninja_grillcore_GrillManager_00024Companion_extSetGrillsCallback",
};

// JNI vtable helpers — precompute function pointers on first use
var jni = null;

function initJNI(env) {
    if (jni) return;
    var vt = env.readPointer();
    jni = {
        GetStringUTFChars:       new NativeFunction(vt.add(169 * 8).readPointer(), 'pointer', ['pointer', 'pointer', 'pointer']),
        ReleaseStringUTFChars:   new NativeFunction(vt.add(170 * 8).readPointer(), 'void',    ['pointer', 'pointer', 'pointer']),
        GetArrayLength:          new NativeFunction(vt.add(171 * 8).readPointer(), 'int',     ['pointer', 'pointer']),
        GetByteArrayElements:    new NativeFunction(vt.add(184 * 8).readPointer(), 'pointer', ['pointer', 'pointer', 'pointer']),
        ReleaseByteArrayElements:new NativeFunction(vt.add(192 * 8).readPointer(), 'void',    ['pointer', 'pointer', 'pointer', 'int']),
    };
    console.log("[*] JNI vtable initialized");
}

function readJStr(env, jstr) {
    if (jstr.isNull()) return "(null)";
    initJNI(env);
    var p = jni.GetStringUTFChars(env, jstr, ptr(0));
    var s = p.readUtf8String();
    jni.ReleaseStringUTFChars(env, jstr, p);
    return s;
}

function readJBytes(env, jarr, maxShow) {
    if (jarr.isNull()) return { hex: "(null)", len: 0 };
    initJNI(env);
    var len = jni.GetArrayLength(env, jarr);
    var buf = jni.GetByteArrayElements(env, jarr, ptr(0));
    maxShow = maxShow || 64;
    var hex = [];
    for (var i = 0; i < Math.min(len, maxShow); i++) {
        hex.push(('0' + buf.add(i).readU8().toString(16)).slice(-2));
    }
    if (len > maxShow) hex.push("...");
    jni.ReleaseByteArrayElements(env, jarr, buf, 0);
    return { hex: hex.join(' '), len: len };
}

var callCount = {};

Object.keys(hooks).forEach(function(shortName) {
    var fullName = hooks[shortName];
    var addr = exportMap[fullName];
    if (!addr) {
        console.log("[!] " + shortName + " not found");
        return;
    }
    var offset = "0x" + addr.sub(mod.base).toString(16);
    callCount[shortName] = 0;

    if (shortName === "extProcessBTData") {
        // (JNIEnv*, jobject, jstring uuid, jbyteArray data, jint rssi)
        Interceptor.attach(addr, {
            onEnter: function(args) {
                callCount[shortName]++;
                console.log("\n=== extProcessBTData #" + callCount[shortName] + " ===");
                try {
                    console.log("  uuid: " + readJStr(args[0], args[2]));
                    var d = readJBytes(args[0], args[3]);
                    console.log("  data (" + d.len + "B): " + d.hex);
                    console.log("  rssi: " + args[4].toInt32());
                } catch(e) {
                    console.log("  (read error: " + e.message + ")");
                }
            }
        });
    } else if (shortName === "extDecryptData") {
        // (JNIEnv*, jobject, jstring uuid, jbyteArray data) -> jbyteArray
        Interceptor.attach(addr, {
            onEnter: function(args) {
                callCount[shortName]++;
                this._env = args[0];
                console.log("\n=== extDecryptData #" + callCount[shortName] + " ===");
                try {
                    console.log("  uuid: " + readJStr(args[0], args[2]));
                    var d = readJBytes(args[0], args[3]);
                    console.log("  ct (" + d.len + "B): " + d.hex);
                } catch(e) {
                    console.log("  (read error: " + e.message + ")");
                }
                AES_ARMED = false;  // Stalker tracing disabled — caused instability; offline analysis instead
                AES_HITS_THIS_CALL = 0;
            },
            onLeave: function(retval) {
                AES_ARMED = false;
                try {
                    if (!retval.isNull()) {
                        var pt = readJBytes(this._env, retval);
                        console.log("  pt (" + pt.len + "B): " + pt.hex);
                    } else {
                        console.log("  pt: (null)");
                    }
                } catch(e) {
                    console.log("  (retval read error: " + e.message + ")");
                }
                console.log("  [AES core hits during this call: " + AES_HITS_THIS_CALL + "]");
            }
        });
    } else if (shortName === "extDecryptDataWithOptionalKey") {
        // (JNIEnv*, jobject, jstring uuid, jbyteArray data, jbyteArray key) -> jbyteArray
        Interceptor.attach(addr, {
            onEnter: function(args) {
                callCount[shortName]++;
                this._env = args[0];
                console.log("\n=== extDecryptDataWithOptionalKey #" + callCount[shortName] + " ===");
                try {
                    console.log("  uuid: " + readJStr(args[0], args[2]));
                    var d = readJBytes(args[0], args[3]);
                    console.log("  ct  (" + d.len + "B): " + d.hex);
                    var k = readJBytes(args[0], args[4], 32);
                    console.log("  KEY (" + k.len + "B): " + k.hex);
                } catch(e) {
                    console.log("  (read error: " + e.message + ")");
                }
            },
            onLeave: function(retval) {
                try {
                    if (!retval.isNull()) {
                        var pt = readJBytes(this._env, retval);
                        console.log("  pt  (" + pt.len + "B): " + pt.hex);
                    } else {
                        console.log("  pt: (null)");
                    }
                } catch(e) {
                    console.log("  (retval read error: " + e.message + ")");
                }
            }
        });
    } else if (shortName === "extEncryptData") {
        Interceptor.attach(addr, {
            onEnter: function(args) {
                callCount[shortName]++;
                this._env = args[0];
                console.log("\n=== extEncryptData #" + callCount[shortName] + " ===");
                try {
                    console.log("  uuid: " + readJStr(args[0], args[2]));
                    var d = readJBytes(args[0], args[3]);
                    console.log("  pt (" + d.len + "B): " + d.hex);
                } catch(e) {
                    console.log("  (read error: " + e.message + ")");
                }
            },
            onLeave: function(retval) {
                try {
                    if (!retval.isNull()) {
                        var ct = readJBytes(this._env, retval);
                        console.log("  ct (" + ct.len + "B): " + ct.hex);
                    }
                } catch(e) {}
            }
        });
    } else if (shortName === "extEncryptDataWithOptionalKey") {
        Interceptor.attach(addr, {
            onEnter: function(args) {
                callCount[shortName]++;
                this._env = args[0];
                console.log("\n=== extEncryptDataWithOptionalKey #" + callCount[shortName] + " ===");
                try {
                    console.log("  uuid: " + readJStr(args[0], args[2]));
                    var d = readJBytes(args[0], args[3]);
                    console.log("  pt  (" + d.len + "B): " + d.hex);
                    var k = readJBytes(args[0], args[4], 32);
                    console.log("  KEY (" + k.len + "B): " + k.hex);
                } catch(e) {
                    console.log("  (read error: " + e.message + ")");
                }
            },
            onLeave: function(retval) {
                try {
                    if (!retval.isNull()) {
                        var ct = readJBytes(this._env, retval);
                        console.log("  ct  (" + ct.len + "B): " + ct.hex);
                    }
                } catch(e) {}
            }
        });
    } else if (shortName === "extSendBTPayload") {
        Interceptor.attach(addr, {
            onEnter: function(args) {
                callCount[shortName]++;
                console.log("\n=== extSendBTPayload #" + callCount[shortName] + " ===");
                try {
                    var d = readJBytes(args[0], args[2]);
                    console.log("  payload (" + d.len + "B): " + d.hex);
                } catch(e) {
                    console.log("  (read error: " + e.message + ")");
                }
            }
        });
    } else {
        // Generic — just log first few calls
        Interceptor.attach(addr, {
            onEnter: function(args) {
                callCount[shortName]++;
                if (callCount[shortName] <= 3) {
                    console.log(">>> " + shortName + " #" + callCount[shortName]);
                }
            }
        });
    }

    console.log("[HOOK] " + shortName + " @ " + offset);
});

// === AES-CBC core hook — GATED: only logs while inside extDecryptData ===
// This address is likely a generic AES primitive used app-wide (TLS etc).
// Logging unconditionally floods the message channel and hangs the app,
// so we only emit output while AES_ARMED is true (set by extDecryptData hook).
var AES_CORE_OFFSET = 0x1760c8;
var aesCoreAddr = mod.base.add(AES_CORE_OFFSET);

function hexAt(addr, len) {
    try {
        var bytes = [];
        for (var i = 0; i < len; i++) bytes.push(('0' + addr.add(i).readU8().toString(16)).slice(-2));
        return bytes.join(' ');
    } catch(e) {
        return "(unreadable)";
    }
}

Interceptor.attach(aesCoreAddr, {
    onEnter: function(args) {
        if (!AES_ARMED) return;
        AES_HITS_THIS_CALL++;
        if (AES_HITS_THIS_CALL > 20) return;  // safety cap even while armed
        console.log("  [AES core] hit #" + AES_HITS_THIS_CALL +
            " x0=" + args[0] + " x1=" + args[1] + " x2=" + args[2] + " x3=" + args[3]);
        for (var i = 0; i < 4; i++) {
            var val = args[i];
            var n = val.toString();
            if (n.indexOf("0x7") === 0 || n.indexOf("0x6") === 0 || n.indexOf("0x5") === 0) {
                console.log("    x" + i + " -> " + hexAt(val, 32));
            }
        }
    }
});
console.log("[HOOK] AES-CBC core (gated) @ 0x" + AES_CORE_OFFSET.toString(16));

// === Candidate hot offsets from Stalker trace — gated, capped, dump regs+mem ===
var CANDIDATE_OFFSETS = [];  // disabled — caused app freeze; revisit offline
var candHitCounts = {};

CANDIDATE_OFFSETS.forEach(function(off) {
    var addr = mod.base.add(off);
    candHitCounts[off] = 0;
    try {
    Interceptor.attach(addr, {
        onEnter: function(args) {
            if (!AES_ARMED) return;
            candHitCounts[off]++;
            if (candHitCounts[off] > 2) return;  // only first 2 hits per session, per offset
            console.log("  [cand 0x" + off.toString(16) + "] hit#" + candHitCounts[off] +
                " x0=" + args[0] + " x1=" + args[1] + " x2=" + args[2] + " x3=" + args[3] +
                " x4=" + args[4] + " x5=" + args[5]);
            for (var i = 0; i < 6; i++) {
                var val = args[i];
                var n = val.toString();
                if (n.indexOf("0x7") === 0 || n.indexOf("0x6") === 0 || n.indexOf("0x5") === 0) {
                    console.log("    x" + i + " -> " + hexAt(val, 48));
                }
            }
        }
    });
    console.log("[HOOK] candidate @ 0x" + off.toString(16));
    } catch(e) {
        console.log("[!] failed to hook candidate 0x" + off.toString(16) + ": " + e.message);
    }
});

console.log("\n[*] All hooks active. Open the app near the grill.");
"use strict";
// Native-level HTTPS plaintext dump — no Java bridge needed (mirrors the
// working approach in frida_hook_btmanager.js: Interceptor.attach directly
// on native exports, since this Gadget build blocks the Java bridge).
//
// Hooks SSL_write/SSL_read in libssl.so (Android's system BoringSSL, used
// by Conscrypt under OkHttp/HttpsURLConnection regardless of app-level
// obfuscation). Reads plaintext buffer AFTER TLS decrypt (SSL_read) or
// BEFORE TLS encrypt (SSL_write) — bypasses cert pinning entirely because
// we're not touching the network layer, just observing app-process memory.

var SENSITIVE_KEYS = /"?(password|pwd|passwd|secret|client_secret|access_token|refresh_token|id_token|authorization|auth)"?\s*[:=]\s*"([^"]*)"/gi;
function redact(text) {
    return text.replace(SENSITIVE_KEYS, function (m, key) {
        return '"' + key + '":"***REDACTED***"';
    });
}

function bytesToText(ptr, len) {
    var buf = ptr.readByteArray(len);
    var arr = new Uint8Array(buf);
    var text = "";
    for (var i = 0; i < arr.length; i++) {
        var c = arr[i];
        text += (c >= 32 && c < 127) ? String.fromCharCode(c) : ".";
    }
    return { arr: arr, text: text };
}

function dump(tag, ptr, len) {
    if (len <= 0) return;
    var n = Math.min(len, 2000);
    var r = bytesToText(ptr, n);
    var safeText = redact(r.text);
    var looksLikeCreds = /password|pwd|passwd/i.test(r.text) && safeText === r.text;
    console.log("[" + tag + "] len=" + len);
    if (looksLikeCreds) {
        console.log("  ***REDACTED (credential-looking payload)***");
    } else {
        console.log("  text: " + safeText);
    }
}

var libssl = Process.findModuleByName("libssl.so");
if (!libssl) {
    console.log("[!] libssl.so not found in process — listing modules with 'ssl' in name:");
    Process.enumerateModules().forEach(function (m) {
        if (m.name.toLowerCase().indexOf("ssl") !== -1 || m.name.toLowerCase().indexOf("crypto") !== -1) {
            console.log("    " + m.name + " @ " + m.base);
        }
    });
} else {
    console.log("[*] libssl.so @ " + libssl.base);
    var pWrite = libssl.findExportByName("SSL_write");
    var pRead = libssl.findExportByName("SSL_read");

    if (pWrite) {
        Interceptor.attach(pWrite, {
            onEnter: function (args) {
                this.buf = args[1];
                this.len = args[2].toInt32();
            },
            onLeave: function (retval) {
                dump("SSL_write", this.buf, this.len);
            }
        });
        console.log("[+] hooked SSL_write @ " + pWrite);
    } else {
        console.log("[!] SSL_write export not found");
    }

    if (pRead) {
        Interceptor.attach(pRead, {
            onEnter: function (args) {
                this.buf = args[1];
            },
            onLeave: function (retval) {
                var n = retval.toInt32();
                if (n > 0) dump("SSL_read", this.buf, n);
            }
        });
        console.log("[+] hooked SSL_read @ " + pRead);
    } else {
        console.log("[!] SSL_read export not found");
    }
}

console.log("[*] Ready (native, no Java bridge). Use the app now.");
