# GATT command crypto — SOLVED (2026-07-06)

**The GATT command cipher is AES-256-CBC (PKCS7).** Proven end-to-end, live.

## How it was cracked
1. The patched app build logs `PAIRING DEBUG encrypt/decrypt data sessionID` —
   the crypto runs synchronously in `grillcore::bt::library`, not behind the
   tokio async wall that blocked the offline emulator.
2. Static disassembly (capstone) of `libgrillcore_android.so` located the cipher:
   it links `aes-0.7.5` + `block-modes-0.8.1` + `block-padding-0.2.1` (bitsliced
   soft AES) → `Cbc<Aes256, Pkcs7>`. The CBC encrypt entry is at **module+0x1315a0**.
3. A Frida hook there (`tools/frida_hook_cbc2.js`) reads the key slice (x1),
   IV slice (x2), and the CBC in/out buffers.
4. **Verification:** for the advertisement channel (whose key we already had),
   `AES-256-CBC-decrypt(key, iv, ciphertext) == plaintext` on 4/4 captured blocks;
   one plaintext block is the grill MAC in the clear. Cipher confirmed.

## Hook ABI (module+0x1315a0, `Cbc<Aes256,Pkcs7>::encrypt`)
- `x1` → `&[u8]` key slice: ptr @ `[x1+8]`, len @ `[x1+16]` (== 0x20 → AES-256).
- `x2` → `&[u8]` IV slice: ptr @ `[x2+8]`, 16 bytes.
- The two 16-byte buffers around the call are (ciphertext, plaintext); the tool
  logs both and Python CBC-decrypt reconciles them.
- AES-256 key schedule is at module+0x114238 (`x1` = raw 32-byte key) — a clean
  spot to read just the key.

## What remains for full HA command control
The per-session GATT key (a non-advert 32-byte AES key) is derived natively from
the per-device `Device_Key` + the 20-byte challenge. Cipher is now known, so:
1. Capture, for ONE GATT command in one session: the session key + IV + the b002
   wire ciphertext, and confirm CBC-decrypt yields a sane command frame.
2. Feed a live `(Device_Key, challenge, session_key)` tuple to
   `tools/crypto_puzzle/derive_solver.py` to recover the KDF `f`, then validate
   against all captured sessions.
3. Reimplement encrypt in pure Python (AES-256-CBC) for the bleak client → HA.

The hard part (which cipher, and getting past the async wall) is done. The KDF is
the last piece, and we now have a reliable live vantage (the CBC hook + key
schedule) to capture the exact tuple it needs.

Device-specific captures (session keys, tuples) live in gitignored
`tools/_re_work/` and are never committed.
