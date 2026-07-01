'use strict';
// Diagnostic: hook EVERY Java_ export of libgrillcore + the AES core, log which fire.
const SO = 'libgrillcore_android.so';
const AES_CORE = 0x1760c8;

function toHex(p, len) {
  if (p.isNull() || len <= 0 || len > 4096) return '<none>';
  try {
    const u8 = new Uint8Array(Memory.readByteArray(p, len));
    let s = ''; for (let i=0;i<u8.length;i++) s += ('0'+u8[i].toString(16)).slice(-2);
    return s;
  } catch (e) { return '<unreadable>'; }
}
function readSlice(p){ try { return { ptr:p.add(8).readPointer(), len:p.add(0x10).readU64().toNumber() }; } catch(e){ return {ptr:ptr(0),len:0}; } }

const seen = {};
function install() {
  const mod = Process.findModuleByName(SO);
  if (!mod) return false;
  console.log('[*] base=' + mod.base);

  // AES core deep hook
  Interceptor.attach(mod.base.add(AES_CORE), {
    onEnter(a){
      const ct=readSlice(a[1]), iv=readSlice(a[2]), key=readSlice(a[3]);
      console.log('\n*** AES sub_1760c8 ***');
      console.log('  KEY('+key.len+'): '+toHex(key.ptr,key.len));
      console.log('  IV ('+iv.len+'): '+toHex(iv.ptr,iv.len));
      console.log('  CT ('+ct.len+'): '+toHex(ct.ptr,ct.len));
      this.out=a[0];
    },
    onLeave(r){ const o=readSlice(this.out); console.log('  PT ('+o.len+'): '+toHex(o.ptr,o.len)); }
  });
  console.log('[+] aes_core hooked');

  // hook all Java_ exports
  let n = 0;
  const exports = mod.enumerateExports();
  for (const e of exports) {
    if (e.type !== 'function') continue;
    if (e.name.indexOf('Java_') !== 0) continue;
    const short = e.name.replace('Java_com_sharkninja_', '').replace('_00024Companion', '');
    try {
      Interceptor.attach(e.address, {
        onEnter(args){
          seen[short] = (seen[short]||0)+1;
          if (seen[short] <= 3) console.log('[CALL] ' + short + ' (#' + seen[short] + ')');
        }
      });
      n++;
    } catch (err) {}
  }
  console.log('[+] hooked ' + n + ' Java_ exports. Watching... (adverts stream automatically)');
  // periodic summary
  setInterval(function(){
    const keys = Object.keys(seen);
    if (keys.length) console.log('--- fired so far: ' + keys.map(k=>k+':'+seen[k]).join(', '));
  }, 5000);
  return true;
}
if (!install()) { const t=setInterval(function(){ if(install()) clearInterval(t); }, 200); }
