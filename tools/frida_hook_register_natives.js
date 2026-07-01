"use strict";

function hexBytes(arr, maxLen) {
    if (!arr) return "(null)";
    var len = Math.min(arr.length, maxLen || 256);
    var hex = [];
    for (var i = 0; i < len; i++) {
        hex.push(('0' + ((arr[i] & 0xff).toString(16))).slice(-2));
    }
    if (arr.length > len) hex.push("...");
    return hex.join(' ');
}

function jbyteArrayToHex(jarr) {
    if (jarr === null) return { hex: "(null)", len: 0 };
    var len = jarr.length;
    var hex = hexBytes(jarr, 256);
    return { hex: hex, len: len };
}

Java.perform(function() {
    console.log("[*] Java.perform entered");

    // --- 1. Hook RegisterNatives ---
    var registerNativesAddr = null;
    var modules = Process.enumerateModules();
    for (var i = 0; i < modules.length; i++) {
        if (modules[i].name.indexOf("libart") !== 0) continue;
        var exps = modules[i].enumerateExports();
        for (var j = 0; j < exps.length; j++) {
            if (exps[j].name.indexOf("RegisterNatives") !== -1 && exps[j].type === "function") {
                registerNativesAddr = exps[j].address;
                console.log("[*] Found RegisterNatives: " + exps[j].name);
                break;
            }
        }
        if (registerNativesAddr) break;
    }

    if (!registerNativesAddr) {
        var env = Java.vm.getEnv();
        var vtable = env.handle.readPointer();
        registerNativesAddr = vtable.add(215 * Process.pointerSize).readPointer();
        console.log("[*] RegisterNatives from vtable: " + registerNativesAddr);
    }

    if (registerNativesAddr) {
        Interceptor.attach(registerNativesAddr, {
            onEnter: function(args) {
                var nMethods = args[3].toInt32();
                var className = "(unknown)";
                try { className = Java.vm.getEnv().getClassName(args[1]); } catch(e) {}

                console.log("\n[RegisterNatives] class=" + className + " count=" + nMethods);
                var sz = Process.pointerSize * 3;
                for (var i = 0; i < nMethods; i++) {
                    var entry = args[2].add(i * sz);
                    var name = entry.readPointer().readUtf8String();
                    var sig = entry.add(Process.pointerSize).readPointer().readUtf8String();
                    var fnPtr = entry.add(Process.pointerSize * 2).readPointer();
                    var mod = Process.findModuleByAddress(fnPtr);
                    var offset = mod ? "0x" + fnPtr.sub(mod.base).toString(16) : fnPtr.toString();
                    console.log("  [" + i + "] " + name + " " + sig + " -> " + offset +
                        (mod ? " (" + mod.name + ")" : ""));
                }
            }
        });
        console.log("[*] RegisterNatives interceptor active");
    }

    // --- 2. Hook BTManager$Companion ---
    try {
        var BTMgr = Java.use("com.sharkninja.grillcore.BTManager$Companion");
        console.log("[*] BTManager$Companion class found");

        BTMgr.processAdvertisementData.implementation = function(uuid, data, rssi) {
            var d = jbyteArrayToHex(data);
            console.log("\n=== processAdvertisementData ===");
            console.log("  uuid : " + uuid);
            console.log("  rssi : " + rssi);
            console.log("  data (" + d.len + "B): " + d.hex);
            this.processAdvertisementData(uuid, data, rssi);
        };
        console.log("[HOOK] processAdvertisementData");

        BTMgr.decryptData.implementation = function(mac, data) {
            var ct = jbyteArrayToHex(data);
            console.log("\n=== decryptData ===");
            console.log("  mac : " + mac);
            console.log("  ct  (" + ct.len + "B): " + ct.hex);
            var result = this.decryptData(mac, data);
            var pt = jbyteArrayToHex(result);
            console.log("  pt  (" + pt.len + "B): " + pt.hex);
            return result;
        };
        console.log("[HOOK] decryptData");

        BTMgr.decryptDataWithOptionalKey.implementation = function(mac, data, key) {
            var ct = jbyteArrayToHex(data);
            var k  = jbyteArrayToHex(key);
            console.log("\n=== decryptDataWithOptionalKey ===");
            console.log("  mac : " + mac);
            console.log("  ct  (" + ct.len + "B): " + ct.hex);
            console.log("  key (" + k.len  + "B): " + k.hex);
            var result = this.decryptDataWithOptionalKey(mac, data, key);
            var pt = jbyteArrayToHex(result);
            console.log("  pt  (" + pt.len + "B): " + pt.hex);
            return result;
        };
        console.log("[HOOK] decryptDataWithOptionalKey");

        BTMgr.encryptData.implementation = function(mac, data) {
            var pt = jbyteArrayToHex(data);
            console.log("\n=== encryptData ===");
            console.log("  mac : " + mac);
            console.log("  pt  (" + pt.len + "B): " + pt.hex);
            var result = this.encryptData(mac, data);
            var ct = jbyteArrayToHex(result);
            console.log("  ct  (" + ct.len + "B): " + ct.hex);
            return result;
        };
        console.log("[HOOK] encryptData");

        BTMgr.encryptDataWithOptionalKey.implementation = function(mac, data, key) {
            var pt = jbyteArrayToHex(data);
            var k  = jbyteArrayToHex(key);
            console.log("\n=== encryptDataWithOptionalKey ===");
            console.log("  mac : " + mac);
            console.log("  pt  (" + pt.len + "B): " + pt.hex);
            console.log("  key (" + k.len  + "B): " + k.hex);
            var result = this.encryptDataWithOptionalKey(mac, data, key);
            var ct = jbyteArrayToHex(result);
            console.log("  ct  (" + ct.len + "B): " + ct.hex);
            return result;
        };
        console.log("[HOOK] encryptDataWithOptionalKey");

    } catch(e) {
        console.log("[!] BTManager$Companion: " + e.message);
    }

    // --- 3. Hook GrillCoreModule ---
    try {
        var GCM = Java.use("com.sharkninja.ninja.connected.kitchen.GrillCoreModule");
        GCM.processAdvertisementData.implementation = function(mac, b64, companyId) {
            console.log("\n>>> GrillCoreModule.processAdvertisementData");
            console.log("  mac       : " + mac);
            console.log("  companyId : " + companyId);
            console.log("  b64       : " + (b64 ? b64.substring(0, 80) : "(null)"));
            this.processAdvertisementData(mac, b64, companyId);
        };
        console.log("[HOOK] GrillCoreModule.processAdvertisementData");
    } catch(e) {
        console.log("[!] GrillCoreModule: " + e.message);
    }

    console.log("\n[*] All hooks active. Use the app — watch for advert data.");
});
