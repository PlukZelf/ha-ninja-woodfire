# ⛔ ROUTE DEAD (2026-07-06): static key is NOT the GATT wire crypto

**Verdict:** the static AES-128-CBC key `sharkninjawp1000` does NOT reach the
BLE wire. Proven offline against known ground truth — do not retry this route.

Test: `tools/crypto_puzzle/static_key_test.py` (run: `python static_key_test.py`
from `tools/crypto_puzzle/`).
- **Definitive (b004 known-plaintext pair):** we have one 64B b004 ciphertext
  whose plaintext we already know (a readable `.&AC000W<serial>...` device-info
  frame; serial redacted — do not commit it).
  NO variant of the static key reproduces it — CBC/static-iv, CBC/zero-iv, ECB,
  and iv-prefix schemes all yield garbage.
- **Corroborating (34× 48B command writes):** all decrypt to max-entropy garbage.
  (One write flagged "plausible" via ECB was a false positive: entropy 5.46 ≈
  max, printable 0.35, PKCS7 matched by chance.)
- Consistent with the handoff's "hard fact" that the 48B writes are max-entropy
  and share 0 bytes — a static key+iv would NOT produce that.

**Conclusion:** answer (a)/(c) below is correct — a **native per-session layer**
wraps the wire. The static JS key `sharkninjawp1000` is the **probe-accessory
crypto**, not the grill command crypto (as `fixtures.py` already suspected).
Next: Spoor 1 Fase 2 (capture raw session_key on phone) or Spoor 2 (Ayla LAN).
See `docs/HANDOFF-volgende-sessie.md`.

---

# (historical) Static AES key found in the RN JS bundle (2026-07-05)

Route: decompiled the React Native Hermes bundle (index.android.bundle) with
hermes-dec -> bundle_decompiled.js (77MB). Traced handleSetTemp -> updateOven,
and sendStartCooking/sendStopCooking -> payload builder -> encryptionData().

## The JS-level command encryption (function `encryptionData`, decompiled line ~650930)
Pure-JS AES via crypto-js:
  KEY  = "sharkninjawp1000"   (UTF-8, 16 bytes)  -> AES-128
       = hex 736861726b6e696e6a61777031303030
  IV   = "1234567890abcdef"   (UTF-8, 16 bytes)
       = hex 31323334353637383930616263646566
  mode = CBC
  padding = Pkcs7
  (key/iv assigned at decompiled lines ~650134/650138; slot5=key, slot6={iv,mode,padding})

encryptionData(bytes): hex-encodes input, CryptoJS.AES.encrypt(Hex.parse(data),
Hex.parse(KEY), {iv, mode:CBC, padding:Pkcs7}) -> returns ciphertext hex.

## Command frame (plaintext, from sendStartCooking @ ~651303 / sendStopCooking)
  hd_info        = SEND_CMD
  hd_sequence    = incrementing counter
  payload_version= 1
  payload_opcode = START_COOKING | STOP_COOKING | (per-command opcode)
  payload_status = 0
  payload_data   = values, OPTIONALLY wrapped by encryptionData() (arg a3/param controls raw vs enc)
  hd_payload_len = payload_data.length + 4
  hd_checksum    = calculteChecksum()   [their spelling]
  -> pack() -> bytes

## TWO encryption layers exist - MUST determine which reaches the wire:
1. JS `encryptionData` (AES-128-CBC, static key "sharkninjawp1000") - inside payload builder.
2. Native `GrillCoreRN.encryptData(bytes, peripheralUuid)` - inside sendBTCommand (per-session, the wall).

OPEN QUESTION (critical): Does the b002 wire write =
  (a) native-encrypt( pack(frame with JS-encrypted payload_data) )   [double layer], or
  (b) just pack(frame)  written raw   [only JS layer, static key = we WIN], or
  (c) native-encrypt( pack(frame with RAW payload_data) )            [JS layer unused for cook]

## Next verification (offline, against known ground truth):
We have captured b002 wire writes (48B) in captures/btsnoop-setcmd-last.log.
Test: can AES-128-CBC(key=sharkninjawp1000, iv=1234567890abcdef) DECRYPT a captured
48B b002 write into a sensible frame (hd_info/opcode/checksum)? 
- If YES -> the static JS key IS the wire crypto. HUGE - pure Python control, no phone.
- If NO  -> the native layer wraps it; the static key is only an inner layer.
