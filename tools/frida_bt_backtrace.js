'use strict';
// Hook Android logging; when the advert log fires, dump a native backtrace
// mapped to libgrillcore_android.so offsets to locate the advert processor.
const SO = 'libgrillcore_android.so';
let mod = null;

function mapAddr(a) {
  if (mod && a.compare(mod.base) >= 0 && a.compare(mod.base.add(mod.size)) < 0)
    return SO + '+0x' + a.sub(mod.base).toString(16);
  const m = Process.findModuleByAddress(a);
  return (m ? m.name : '?') + '@' + a;
}

function dumpBt(ctx, label) {
  try {
    const bt = Thread.backtrace(ctx, Backtracer.FUZZY).map(mapAddr);
    console.log('  BT[' + label + ']:');
    bt.slice(0, 12).forEach(function (f) { console.log('    ' + f); });
  } catch (e) { console.log('  bt err ' + e); }
}

function install() {
  mod = Process.findModuleByName(SO);
  if (!mod) return false;
  console.log('[*] base=' + mod.base + ' size=0x' + mod.size.toString(16));

  function hookLog(name, msgArgIndex) {
    const p = Module.findGlobalExportByName ? Module.findGlobalExportByName(name)
                                            : Module.getExportByName(null, name);
    if (!p) { console.log('[!] no ' + name); return; }
    Interceptor.attach(p, {
      onEnter(a) {
        try {
          const msg = a[msgArgIndex].readCString();
          if (msg && (msg.indexOf('adv pkt') >= 0 || msg.indexOf('received adv') >= 0 ||
                      msg.indexOf('calculated grill state') >= 0)) {
            console.log('\n[LOG ' + name + '] ' + msg.slice(0, 80));
            dumpBt(this.context, name);
          }
        } catch (e) {}
      }
    });
    console.log('[+] hooked ' + name + ' @ ' + p);
  }
  // __android_log_write(prio, tag, text)  -> text = arg2
  hookLog('__android_log_write', 2);
  // __android_log_print(prio, tag, fmt, ...) -> fmt = arg2
  hookLog('__android_log_print', 2);
  // __android_log_buf_write(bufID, prio, tag, text) -> text = arg3
  hookLog('__android_log_buf_write', 3);

  // structured logger: __android_log_write_log_message(__android_log_message*)
  // struct: {size, version, buffer_id, priority, tag*, file*, line, message*}
  const wlm = Module.findGlobalExportByName
      ? Module.findGlobalExportByName('__android_log_write_log_message')
      : Module.getExportByName(null, '__android_log_write_log_message');
  if (wlm) {
    Interceptor.attach(wlm, {
      onEnter(a) {
        try {
          // message* is the last pointer field; probe a few offsets
          const s = a[0];
          for (const off of [0x28, 0x30, 0x20, 0x38]) {
            const mp = s.add(off).readPointer();
            const msg = mp.readCString();
            if (msg && (msg.indexOf('adv pkt') >= 0 || msg.indexOf('calculated grill') >= 0)) {
              console.log('\n[WLM @+0x' + off.toString(16) + '] ' + msg.slice(0, 80));
              dumpBt(this.context, 'wlm');
              break;
            }
          }
        } catch (e) {}
      }
    });
    console.log('[+] hooked __android_log_write_log_message @ ' + wlm);
  } else { console.log('[!] no __android_log_write_log_message'); }
  return true;
}
if (!install()) { const t = setInterval(function () { if (install()) clearInterval(t); }, 200); }
