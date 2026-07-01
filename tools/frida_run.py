#!/usr/bin/env python3
"""Attach Frida to the gadget-injected Ninja app and run a hook script,
printing all console output (key/IV/CT/PT dumps) to stdout.

This app's Frida Gadget build blocks the Java bridge, so hook scripts must
attach directly to native exports (Interceptor.attach), not Java.perform —
see frida_hook_btmanager.js / frida_ssl_native_dump.js for the working
pattern. setTimeout/setInterval also do not fire in this Gadget's JS
runtime; avoid polling loops in hook scripts.

Usage:
  python frida_run.py <script.js>
"""
import os
import sys
import time
import frida

SCRIPT = sys.argv[1] if len(sys.argv) > 1 else \
    os.path.join(os.path.dirname(__file__), "frida_hook_btmanager.js")

def on_message(msg, data):
    if msg.get("type") == "log":
        print(msg["payload"], flush=True)
    elif msg.get("type") == "error":
        print("[JS ERROR] " + msg.get("stack", str(msg)), flush=True)
    else:
        print("[MSG] " + str(msg), flush=True)

device = frida.get_usb_device(timeout=10)
print("[*] device: " + device.name, flush=True)

# Attach to the Gadget (named 'Gadget' by frida-gadget), fall back to package.
target = None
for name in ("Gadget", "com.sharkninja.ninja.connected.kitchen"):
    try:
        target = device.attach(name)
        print("[*] attached to: " + name, flush=True)
        break
    except Exception as e:
        print(f"[!] attach {name} failed: {e}", flush=True)
if target is None:
    sys.exit("could not attach")

with open(SCRIPT, "r", encoding="utf-8") as f:
    code = f.read()
script = target.create_script(code)
script.on("message", on_message)
script.load()
print("[*] script loaded -- waiting for crypto activity. Use the app now.", flush=True)

# stay alive
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    pass
