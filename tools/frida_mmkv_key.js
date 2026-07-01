"use strict";
// Extract the react-native-mmkv crypt key WITHOUT restart fragility.
// Polls for libreactnativemmkv (no dlopen hook → no linker deadlock), then hooks
// AESCrypt::decrypt and reads the key out of the live AESCrypt via AESCrypt::getKey().

var LIB = "libreactnativemmkv.so";
var installed = false;
var captured = false;

function hexAt(p, n) {
    try { var b=[]; for (var i=0;i<n;i++) b.push(('0'+p.add(i).readU8().toString(16)).slice(-2)); return b.join(' '); }
    catch(e){ return "(unreadable)"; }
}
function asText(p, n) {
    try { var s=""; for (var i=0;i<n;i++){var c=p.add(i).readU8(); s+=(c>=0x20&&c<0x7f)?String.fromCharCode(c):".";} return s; }
    catch(e){ return "(unreadable)"; }
}

function install() {
    if (installed) return true;
    var mod = Process.findModuleByName(LIB);
    if (!mod) return false;
    installed = true;
    console.log("[*] " + LIB + " @ " + mod.base);

    var exp = {};
    mod.enumerateExports().forEach(function (e) { if (e.type === "function") exp[e.name] = e.address; });

    var pGetKey  = exp["_ZNK4mmkv8AESCrypt6getKeyEPv"];       // AESCrypt::getKey(void*) const
    var pDecrypt = exp["_ZN4mmkv8AESCrypt7decryptEPKvPvm"];   // AESCrypt::decrypt(const void*, void*, size_t)
    var pEncrypt = exp["_ZN4mmkv8AESCrypt7encryptEPKvPvm"];

    if (!pGetKey)  { console.log("[!] getKey export missing"); }
    if (!pDecrypt) { console.log("[!] decrypt export missing"); }

    var getKey = pGetKey ? new NativeFunction(pGetKey, "void", ["pointer", "pointer"]) : null;
    var keyBuf = Memory.alloc(64);

    function dumpKeyFrom(aesCryptThis, tag) {
        if (captured) return;
        if (!getKey) return;
        try {
            // Zero the buffer, then let getKey copy the key in.
            keyBuf.writeByteArray(new Array(64).fill(0));
            getKey(aesCryptThis, keyBuf);
            // MMKV crypt keys are up to 16 bytes; find printable/used length.
            var hex16 = hexAt(keyBuf, 16);
            var txt16 = asText(keyBuf, 16);
            console.log("\n================ MMKV CRYPT KEY (" + tag + ") ================");
            console.log("  key(hex, 16B): " + hex16);
            console.log("  key(txt, 16B): \"" + txt16 + "\"");
            console.log("  key(hex, 32B): " + hexAt(keyBuf, 32));
            console.log("============================================================");
            captured = true;
        } catch (e) {
            console.log("[!] getKey failed: " + e.message);
        }
    }

    if (pDecrypt) {
        Interceptor.attach(pDecrypt, {
            onEnter: function (args) { dumpKeyFrom(args[0], "decrypt"); }
        });
        console.log("[HOOK] AESCrypt::decrypt");
    }
    if (pEncrypt) {
        Interceptor.attach(pEncrypt, {
            onEnter: function (args) { dumpKeyFrom(args[0], "encrypt"); }
        });
        console.log("[HOOK] AESCrypt::encrypt");
    }

    // KeyValueHolderCrypt::toMMBuffer(const void* basePtr, const AESCrypt* crypter) const
    // Fires on EVERY read of an encrypted value → x2 is the live AESCrypt. Most reliable trigger.
    var pToMMBuffer = exp["_ZNK4mmkv19KeyValueHolderCrypt10toMMBufferEPKvPKNS_8AESCryptE"];
    if (pToMMBuffer) {
        Interceptor.attach(pToMMBuffer, {
            onEnter: function (args) { dumpKeyFrom(args[2], "toMMBuffer"); }
        });
        console.log("[HOOK] KeyValueHolderCrypt::toMMBuffer");
    } else {
        console.log("[!] toMMBuffer export not found");
    }

    // CodedInputDataCrypt ctor takes an AESCrypt& too (used while decoding the map).
    // _ZN4mmkv19CodedInputDataCryptC1EPKvmRNS_8AESCryptE (this, ptr, size, AESCrypt&)
    ["_ZN4mmkv19CodedInputDataCryptC1EPKvmRNS_8AESCryptE",
     "_ZN4mmkv19CodedInputDataCryptC2EPKvmRNS_8AESCryptE"].forEach(function (sym) {
        var p = exp[sym];
        if (p) {
            Interceptor.attach(p, { onEnter: function (args) { dumpKeyFrom(args[3], "CIDCrypt"); } });
            console.log("[HOOK] " + sym);
        }
    });

    // Also hook mmkvWithID to see the mmapID + cryptKey string (if it gets called again).
    var mmkvWithID = exp["_ZN4MMKV10mmkvWithIDERKNSt6__ndk112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEEi8MMKVModePS6_SA_m"];
    if (mmkvWithID) {
        Interceptor.attach(mmkvWithID, {
            onEnter: function (args) {
                function rdStr(ptr) {
                    try {
                        var first = ptr.readU8();
                        if ((first & 1) === 0) return { s: ptr.add(1).readUtf8String(first>>1), raw: ptr.add(1), len: first>>1 };
                        var size = ptr.add(8).readU64().toNumber(); var dat = ptr.add(16).readPointer();
                        return { s: dat.readUtf8String(size), raw: dat, len: size };
                    } catch(e){ return { s:"(err)", len:0 }; }
                }
                var id = rdStr(args[0]);
                var line = "[mmkvWithID] id=\"" + id.s + "\"";
                if (!args[3].isNull()) { var ck = rdStr(args[3]); line += "  cryptKey(hex)=" + hexAt(ck.raw, ck.len) + " (\"" + ck.s + "\")"; }
                else line += "  cryptKey=NULL";
                console.log(line);
            }
        });
        console.log("[HOOK] MMKV::mmkvWithID");
    }

    console.log("\n[*] Armed. Now actively forcing a re-decrypt of sn_storage...");

    // --- Active trigger: get the sn_storage MMKV instance and force loadFromFile() ---
    try {
        var pMmkvWithID = exp["_ZN4MMKV10mmkvWithIDERKNSt6__ndk112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEEi8MMKVModePS6_SA_m"];
        var pLoadFromFile = exp["_ZN4MMKV12loadFromFileEv"];
        var pClearCache = exp["_ZN4MMKV16clearMemoryCacheEb"];
        var pCount = exp["_ZN4MMKV5countEb"];
        if (!pMmkvWithID || !pLoadFromFile) {
            console.log("[!] mmkvWithID/loadFromFile missing — can't force. Waiting for app read instead.");
            return true;
        }
        var mmkvWithIDFn = new NativeFunction(pMmkvWithID, "pointer",
            ["pointer", "int", "int", "pointer", "pointer", "uint64"]);
        var loadFromFileFn = new NativeFunction(pLoadFromFile, "void", ["pointer"]);
        var clearCacheFn = pClearCache ? new NativeFunction(pClearCache, "void", ["pointer", "int"]) : null;

        // Read DEFAULT_MMAP_SIZE global if available (else 4096).
        var mmapSize = 4096;
        try { var g = exp["_ZN4mmkv17DEFAULT_MMAP_SIZEE"]; if (g) { var v = g.readS32(); if (v > 0) mmapSize = v; } } catch (e) {}

        // Build libc++ std::string "sn_storage" (SSO short-string: byte0 = len<<1, data at +1).
        function makeStdString(str) {
            var buf = Memory.alloc(24);
            buf.writeByteArray(new Array(24).fill(0));
            if (str.length <= 22) {
                buf.writeU8(str.length << 1);
                buf.add(1).writeUtf8String(str);
            }
            return buf;
        }
        var idStr = makeStdString("sn_storage");

        var mmkvPtr = mmkvWithIDFn(idStr, mmapSize, 0, ptr(0), ptr(0), 0);
        console.log("[*] mmkvWithID(\"sn_storage\") -> " + mmkvPtr);
        if (!mmkvPtr.isNull()) {
            if (clearCacheFn) { clearCacheFn(mmkvPtr, 1); console.log("[*] clearMemoryCache done"); }
            loadFromFileFn(mmkvPtr);   // re-reads & decrypts whole file → decrypt/toMMBuffer hook fires
            console.log("[*] loadFromFile done");
        }
    } catch (e) {
        console.log("[!] active trigger failed: " + e.message + "\n" + e.stack);
    }

    return true;
}

// Poll for the library (safe — no linker lock interaction).
if (!install()) {
    console.log("[*] " + LIB + " not loaded yet — polling every 500ms...");
    var tries = 0;
    var timer = setInterval(function () {
        tries++;
        if (install() || tries > 120) clearInterval(timer);
    }, 500);
}
