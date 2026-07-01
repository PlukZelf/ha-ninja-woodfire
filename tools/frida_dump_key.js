/*
 * frida_dump_key.js  --  Dump the Ninja Woodfire BLE AES session key/IV/data
 *
 * Hooks the AES-CBC primitives inside libgrillcore_android.so to capture the
 * session key, IV, ciphertext and resulting plaintext as the official app talks
 * to the grill.  This gives ground-truth to decrypt captured frames and to learn
 * whether the key is static or per-session.
 *
 * Function offsets (file vaddr; the .so maps vaddr 0 -> module base):
 *   sub_1760c8  AES-CBC core. args: x0=out, x1=ciphertext, x2=IV, x3=key.
 *               each of x1/x2/x3 is a 24-byte slice {meta@+0, ptr@+8, len@+0x10}.
 *   sub_175fec  AES-CBC wrapper (x4 = key material).
 *   extDecryptData / extEncryptData / extProcessBTData JNI entry points (context).
 *
 * App package: com.sharkninja.ninja.connected.kitchen
 *
 * Rooted phone + frida-server:
 *   frida -U -f com.sharkninja.ninja.connected.kitchen -l frida_dump_key.js --no-pause
 * Attach to the already-running app:
 *   frida -U -n "Ninja" -l frida_dump_key.js
 * Gadget-repackaged APK (via tools/bypass_frida_detection.sh):
 *   frida -U Gadget -l frida_dump_key.js
 *
 * If the app detects Frida, run tools/bypass_frida_detection.sh first.
 */

'use strict';

const SO = 'libgrillcore_android.so';

// file vaddr offsets within the .so
const OFF = {
  aes_core:        0x1760c8,  // sub_1760c8
  aes_wrapper:     0x175fec,  // sub_175fec
  key_setup:       0x1754d8,  // sub_1754d8
};
// JNI exports (full mangled names)
const JNI = {
  extDecryptData:    'Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptData',
  extEncryptData:    'Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptData',
  extDecryptDataOpt: 'Java_com_sharkninja_grillcore_BTManager_00024Companion_extDecryptDataWithOptionalKey',
  extEncryptDataOpt: 'Java_com_sharkninja_grillcore_BTManager_00024Companion_extEncryptDataWithOptionalKey',
  extProcessBTData:  'Java_com_sharkninja_grillcore_BTManager_00024Companion_extProcessBTData',
  extSendBTPayload:  'Java_com_sharkninja_grillcore_BTManager_00024Companion_extSendBTPayload',
  wsOnDataReceived:  'Java_com_sharkninja_api_mantleutilities_WebSocketManager_00024Companion_extOnDataReceived',
};

function hexdump_ptr(p, len) {
  if (p.isNull() || len === 0 || len > 4096) return '<none>';
  try { return Memory.readByteArray(p, len); } catch (e) { return '<unreadable>'; }
}

function toHex(p, len) {
  const buf = hexdump_ptr(p, len);
  if (typeof buf === 'string') return buf;
  const u8 = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < u8.length; i++) s += ('0' + u8[i].toString(16)).slice(-2);
  return s;
}

// read a Rust slice struct {meta, ptr, len} (24 bytes) -> {ptr, len}
function readSlice(structPtr) {
  try {
    const ptr = structPtr.add(8).readPointer();
    const len = structPtr.add(0x10).readU64().toNumber();
    return { ptr, len };
  } catch (e) { return { ptr: ptr(0), len: 0 }; }
}

let keysSeen = {};

function install() {
  // Frida 17 module API: Process.findModuleByName(...) -> Module | null
  const mod = Process.findModuleByName(SO);
  if (mod === null) { console.log('[!] ' + SO + ' not loaded yet'); return false; }
  const base = mod.base;
  console.log('[*] ' + SO + ' base = ' + base);

  // --- AES core: the money hook ---
  Interceptor.attach(base.add(OFF.aes_core), {
    onEnter(args) {
      // x0=out, x1=ciphertext slice, x2=IV slice, x3=key slice
      this.out = args[0];
      const ct  = readSlice(args[1]);
      const iv  = readSlice(args[2]);
      const key = readSlice(args[3]);
      const keyHex = toHex(key.ptr, key.len);
      const ivHex  = toHex(iv.ptr, iv.len);
      const ctHex  = toHex(ct.ptr, ct.len);
      this.keyHex = keyHex;
      const firstTime = !(keyHex in keysSeen);
      keysSeen[keyHex] = (keysSeen[keyHex] || 0) + 1;
      console.log('\n=== AES sub_1760c8 ===' + (firstTime ? '  *** NEW KEY ***' : ''));
      console.log('  KEY (' + key.len + 'B): ' + keyHex);
      console.log('  IV  (' + iv.len  + 'B): ' + ivHex);
      console.log('  CT  (' + ct.len  + 'B): ' + ctHex);
    },
    onLeave(retval) {
      // output Vec at this.out: {meta, ptr, len}
      try {
        const o = readSlice(this.out);
        console.log('  PT  (' + o.len + 'B): ' + toHex(o.ptr, o.len));
      } catch (e) {}
      console.log('  distinct keys so far: ' + Object.keys(keysSeen).length);
    }
  });
  console.log('[+] hooked aes_core @ ' + base.add(OFF.aes_core));

  // --- JNI context hooks (which uuid / data drives each crypto op) ---
  for (const name in JNI) {
    const addr = mod.findExportByName(JNI[name]);
    if (addr) {
      Interceptor.attach(addr, {
        onEnter(a) { console.log('[JNI] ' + name); }
      });
      console.log('[+] hooked ' + name + ' @ ' + addr);
    } else {
      console.log('[!] export not found: ' + name);
    }
  }
  return true;
}

// The .so may load after the app starts; retry until present.
if (!install()) {
  const iv = setInterval(function () {
    if (install()) clearInterval(iv);
  }, 200);
}
