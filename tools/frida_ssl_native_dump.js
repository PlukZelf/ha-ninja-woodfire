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
