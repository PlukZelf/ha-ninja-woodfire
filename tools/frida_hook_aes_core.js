"use strict";
// Hook the AES-CBC core at 0x1760c8 (identified via static analysis in REBOOT.md)
// This fires during the GATT decrypt path (extDecryptData), not BLE adverts.
// Dump all pointer-like register args as both raw hex and attempt key/IV reads.

var mod = Process.findModuleByName("libgrillcore_android.so");
if (!mod) {
    console.log("[!] libgrillcore_android.so not found");
} else {
    console.log("[*] lib @ " + mod.base);
}

var AES_CORE_OFFSET = 0x1760c8;
var aesCoreAddr = mod.base.add(AES_CORE_OFFSET);

function hexAt(addr, len) {
    try {
        var bytes = [];
        for (var i = 0; i < len; i++) bytes.push(('0' + addr.add(i).readU8().toString(16)).slice(-2));
        return bytes.join(' ');
    } catch(e) {
        return "(unreadable: " + e.message + ")";
    }
}

var callCount = 0;

Interceptor.attach(aesCoreAddr, {
    onEnter: function(args) {
        callCount++;
        console.log("\n=== AES-CBC core #" + callCount + " @ 0x" + AES_CORE_OFFSET.toString(16) + " ===");
        // Dump x0-x6 as both raw pointer values and attempt to read as buffers
        for (var i = 0; i < 7; i++) {
            var val = args[i];
            console.log("  x" + i + " = " + val);
            // Try reading 32 bytes from this if it looks like a heap pointer
            var n = val.toString();
            if (n.indexOf("0x7") === 0 || n.indexOf("0x6") === 0 || n.indexOf("0x5") === 0) {
                console.log("    -> " + hexAt(val, 32));
            }
        }
        this.args0 = args[0];
        this.args1 = args[1];
        this.args2 = args[2];
        this.args3 = args[3];
    },
    onLeave: function(retval) {
        console.log("  retval = " + retval);
    }
});

console.log("[HOOK] AES-CBC core @ 0x" + AES_CORE_OFFSET.toString(16));

// Also hook extDecryptData to bracket the calls and give context
var pDecrypt = null;
mod.enumerateExports().forEach(function(e) {
    if (e.name === "Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData") {
        pDecrypt = e.address;
    }
});

if (pDecrypt) {
    Interceptor.attach(pDecrypt, {
        onEnter: function(args) {
            console.log("\n[*] >>> extDecryptData ENTER <<<");
        },
        onLeave: function(retval) {
            console.log("[*] >>> extDecryptData LEAVE <<<");
        }
    });
    console.log("[HOOK] extDecryptData (bracket)");
}

console.log("\n[*] Ready. Trigger a GATT connect/decrypt in the app (tap the grill to connect).");
