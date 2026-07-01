'use strict';
// Hook the advert AES-CTR/AEAD core at file vaddr 0x1f4694 in libgrillcore.
// At entry: x0 = AES key schedule (first 16 bytes = AES-128 key),
//           x1 = {+0x00: counter/nonce ptr, +0x08: input ptr, +0x10: output ptr, +0x18: nblocks}
const SO = 'libgrillcore_android.so';
const AEAD = 0x1f4694;

function hex(p, len) {
  if (p.isNull() || len <= 0 || len > 8192) return '<none>';
  try {
    const u8 = new Uint8Array(Memory.readByteArray(p, len));
    let s=''; for (let i=0;i<u8.length;i++) s += ('0'+u8[i].toString(16)).slice(-2);
    return s;
  } catch (e) { return '<unreadable:'+e+'>'; }
}

const seenKeys = {};
function install() {
  const mod = Process.findModuleByName(SO);
  if (!mod) return false;
  const addr = mod.base.add(AEAD);
  console.log('[*] base=' + mod.base + '  hooking AEAD core @ ' + addr);
  Interceptor.attach(addr, {
    onEnter(a) {
      this.x0 = a[0]; this.x1 = a[1];
      try {
        const ksched = a[0];
        const ctrPtr = a[1].add(0).readPointer();
        const inPtr  = a[1].add(0x08).readPointer();
        this.outPtr  = a[1].add(0x10).readPointer();
        const nblk   = a[1].add(0x18).readU64().toNumber();
        this.nblk = nblk;
        const key = hex(ksched, 16);
        const novel = !(key in seenKeys);
        seenKeys[key] = (seenKeys[key]||0)+1;
        console.log('\n=== AEAD/CTR @0x1f4694 ===' + (novel ? '  *** NEW KEY ***' : ''));
        console.log('  KEY[0:16] (raw?): ' + key);
        console.log('  KEYSCHED[0:48]:   ' + hex(ksched, 48));
        console.log('  NONCE/CTR[0:16]:  ' + hex(ctrPtr, 16));
        console.log('  IN  ('+(nblk*16)+'B): ' + hex(inPtr, nblk*16));
        console.log('  distinct keys: ' + Object.keys(seenKeys).length);
      } catch (e) { console.log('  [onEnter err] ' + e); }
    },
    onLeave(r) {
      try { console.log('  OUT ('+(this.nblk*16)+'B): ' + hex(this.outPtr, this.nblk*16)); }
      catch (e) {}
    }
  });
  console.log('[+] hooked. Adverts decrypt ~1/sec; watching...');
  return true;
}
if (!install()) { const t=setInterval(function(){ if(install()) clearInterval(t); }, 200); }
