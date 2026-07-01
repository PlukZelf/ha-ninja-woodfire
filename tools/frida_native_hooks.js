"use strict";
// Native-level hooks for libgrillcore_android.so
// Works without Java bridge (Frida Gadget mode)

var mod = Process.findModuleByName("libgrillcore_android.so");
if (!mod) {
    // Try to find it
    var mods = Process.enumerateModules();
    for (var i = 0; i < mods.length; i++) {
        if (mods[i].name.indexOf("grillcore") !== -1) {
            mod = mods[i];
            break;
        }
    }
}

if (!mod) {
    console.log("[!] libgrillcore_android.so not loaded yet");
    console.log("[*] Loaded modules:");
    Process.enumerateModules().forEach(function(m) {
        console.log("  " + m.name + " @ " + m.base);
    });
} else {
    console.log("[*] Found " + mod.name + " @ " + mod.base + " (" + mod.size + " bytes)");

    // List all exports from the library
    console.log("\n[*] Exports:");
    var exports = mod.enumerateExports();
    exports.forEach(function(e) {
        console.log("  " + e.type + " " + e.name + " @ 0x" + e.address.sub(mod.base).toString(16));
    });

    // Look for JNI_OnLoad (should be exported)
    var jniOnLoad = exports.filter(function(e) { return e.name === "JNI_OnLoad"; });
    if (jniOnLoad.length > 0) {
        console.log("\n[*] JNI_OnLoad found @ 0x" + jniOnLoad[0].address.sub(mod.base).toString(16));
    }

    // Search for known strings to verify we have the right module
    console.log("\n[*] Searching for known strings...");
    var patterns = [
        { name: "received adv pkt", offset: 0x7ec8f },
        { name: "AEAD tag mismatch", offset: 0x84254 },
        { name: "adv pkt for uuid",  offset: 0x7ec98 },
    ];

    patterns.forEach(function(p) {
        try {
            var addr = mod.base.add(p.offset);
            var str = addr.readUtf8String();
            console.log("  0x" + p.offset.toString(16) + ": \"" + str.substring(0, 40) + "\"");
        } catch(e) {
            console.log("  0x" + p.offset.toString(16) + ": (unreadable: " + e.message + ")");
        }
    });

    // Hook all Java_ exports (even though we know they don't fire for adverts,
    // let's enumerate them to confirm RegisterNatives is used)
    var javaExports = exports.filter(function(e) { return e.name.indexOf("Java_") === 0; });
    console.log("\n[*] Java_ exports: " + javaExports.length);
    javaExports.forEach(function(e) {
        console.log("  " + e.name);
    });

    // Now let's find RegisterNatives calls by scanning for xrefs to the string
    // "extProcessBTData" in the binary
    console.log("\n[*] Scanning for 'extProcessBTData' string in module...");
    var matches = Memory.scanSync(mod.base, mod.size,
        // "extProcessBTData" as hex
        "65 78 74 50 72 6f 63 65 73 73 42 54 44 61 74 61");
    matches.forEach(function(m) {
        var offset = m.address.sub(mod.base);
        console.log("  Found @ 0x" + offset.toString(16));
        // Read the full string
        console.log("  Value: \"" + m.address.readUtf8String() + "\"");
    });

    // Also scan for extDecryptData
    console.log("\n[*] Scanning for 'extDecryptData' string...");
    var matches2 = Memory.scanSync(mod.base, mod.size,
        "65 78 74 44 65 63 72 79 70 74 44 61 74 61 00");
    matches2.forEach(function(m) {
        var offset = m.address.sub(mod.base);
        console.log("  Found @ 0x" + offset.toString(16) + ": \"" + m.address.readUtf8String() + "\"");
    });

    // Scan for all ext* method name strings
    console.log("\n[*] Scanning for all 'ext' prefixed strings...");
    var extMatches = Memory.scanSync(mod.base, mod.size, "65 78 74");  // "ext"
    var seen = {};
    extMatches.forEach(function(m) {
        try {
            var s = m.address.readUtf8String();
            if (s && s.length > 3 && s.length < 50 && s.indexOf("ext") === 0 && !seen[s]) {
                seen[s] = true;
                var offset = m.address.sub(mod.base);
                console.log("  0x" + offset.toString(16) + ": \"" + s + "\"");
            }
        } catch(e) {}
    });
}
