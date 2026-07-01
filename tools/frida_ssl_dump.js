"use strict";
// Dump plaintext HTTPS traffic by hooking Android's Conscrypt SSL layer
// (com.android.org.conscrypt.NativeCrypto.SSL_write/SSL_read and friends).
// Works regardless of HTTP client (OkHttp/Retrofit/etc) and bypasses cert
// pinning concerns because we read the data AFTER TLS decrypt / BEFORE encrypt,
// inside the app's own process — no MITM proxy or CA install needed.
//
// Goal: capture whether the app talks to a Ninja cloud endpoint during
// login/pairing, and if so, what's in the request/response (looking for any
// device key / shared secret / session material tied to the BLE handshake).

console.log("[*] frida_ssl_dump.js top-level eval starting");

// setTimeout/setInterval do not fire in this Gadget environment, so no polling —
// call Java.perform directly (app must already be fully started, ART initialized).
Java.perform(function () {
    console.log("[*] frida_ssl_dump: attaching to NativeCrypto...");

    // Redact obvious credential/secret fields before anything is ever logged.
    var SENSITIVE_KEYS = /"?(password|pwd|passwd|secret|client_secret|access_token|refresh_token|id_token|authorization|auth)"?\s*[:=]\s*"([^"]*)"/gi;
    function redact(text) {
        return text.replace(SENSITIVE_KEYS, function (m, key) {
            return '"' + key + '":"***REDACTED***"';
        });
    }

    function tryHook(className, methodName, argIndexes) {
        try {
            var Cls = Java.use(className);
            var overloads = Cls[methodName].overloads;
            overloads.forEach(function (ov) {
                ov.implementation = function () {
                    var args = Array.prototype.slice.call(arguments);
                    var ret = ov.apply(this, args);
                    try {
                        argIndexes.forEach(function (i) {
                            var buf = args[i];
                            if (buf && buf.length !== undefined) {
                                var bytes = [];
                                for (var j = 0; j < buf.length; j++) bytes.push(buf[j] & 0xff);
                                var arr = new Uint8Array(bytes);
                                var text = "";
                                for (var k = 0; k < arr.length; k++) {
                                    var c = arr[k];
                                    text += (c >= 32 && c < 127) ? String.fromCharCode(c) : ".";
                                }
                                var safeText = redact(text);
                                var looksLikeCreds = /password|pwd|passwd/i.test(text) && safeText === text;
                                console.log("[SSL " + methodName + "] len=" + arr.length);
                                if (looksLikeCreds) {
                                    console.log("  hex : ***REDACTED (credential-looking payload)***");
                                    console.log("  text: ***REDACTED (credential-looking payload)***");
                                } else {
                                    console.log("  hex : " + Array.from(arr).map(b => b.toString(16).padStart(2, "0")).join(" ").substring(0, 600));
                                    console.log("  text: " + safeText.substring(0, 600));
                                }
                            }
                        });
                    } catch (e) {
                        console.log("[!] dump error: " + e);
                    }
                    return ret;
                };
            });
            console.log("[+] hooked " + className + "." + methodName);
            return true;
        } catch (e) {
            return false;
        }
    }

    // Try a spread of known signatures across Android/Conscrypt versions.
    var hookedAny = false;
    hookedAny = tryHook("com.android.org.conscrypt.NativeCrypto", "SSL_write", [2]) || hookedAny;
    hookedAny = tryHook("com.android.org.conscrypt.NativeCrypto", "SSL_read", [2]) || hookedAny;
    hookedAny = tryHook("com.android.org.conscrypt.NativeCrypto", "ENGINE_SSL_write_BIO", [2]) || hookedAny;
    hookedAny = tryHook("com.android.org.conscrypt.NativeCrypto", "ENGINE_SSL_read_BIO", [2]) || hookedAny;

    if (!hookedAny) {
        console.log("[!] no NativeCrypto hooks attached — class/method names may differ on this build.");
        console.log("[*] falling back to OkHttp-level hook (RealCall / Interceptor).");
        try {
            var RealCall = Java.use("okhttp3.RealCall");
            RealCall.execute.implementation = function () {
                var req = this.request();
                console.log("[OkHttp] -> " + req.method() + " " + req.url().toString());
                var resp = this.execute();
                console.log("[OkHttp] <- " + resp.code() + " " + resp.request().url().toString());
                return resp;
            };
            console.log("[+] hooked okhttp3.RealCall.execute");
        } catch (e) {
            console.log("[!] OkHttp fallback also failed: " + e);
        }
    }

    console.log("[*] Ready. Now open the Ninja app on the phone and go through login / device pairing.");
});
