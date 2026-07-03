# BLE Crypto — Reverse Engineering Status

_Last updated: 2026-07-02_

This document records what is known about the encryption used on the
Ninja Woodfire Pro BLE link (advertisements and GATT), based on static
analysis of `libgrillcore_android.so` plus targeted dynamic verification.

> Supersedes an earlier version of this document from 2026-06-28, which was
> based on a **different app build** (different function offsets, e.g.
> `extDecryptData` at `0x142560` there vs `0x10401c` in the build analyzed
> below) — always confirm the binary in hand matches the currently installed
> app (pull it fresh via `adb`, verify with `tools/elf_symbols.py`) before
> reusing recorded offsets.

## Binary under analysis

Pulled directly from the installed app on device (`adb pull` on the `pm
path` result), NOT reused from an older capture — this matters, see the
warning above.

| Property | Value |
| --- | --- |
| File | `libgrillcore_android.so` |
| Arch | ELF64 AArch64 |
| Size | 4,678,184 bytes |
| Verified via | `tools/elf_symbols.py` `.dynsym` parse — `extProcessBTData` vaddr `0x10ae40` matches live Frida-captured runtime offset exactly |

## Two separate crypto surfaces: adverts vs GATT

The BLE advertisement channel and the post-`Connect` GATT channel use
**unrelated crypto**, both AES-based, with different (and differently
solved) key situations:

| | Advertisements | GATT (post-Connect) |
| --- | --- | --- |
| Key | **Static**, embedded as constants in the `.so` | **Per-session**, negotiated fresh on every `Connect`, held only in-memory (not persisted to disk on either side) |
| Status | ✅ Fully decoded (see below) | ❌ Unsolved — out of scope for a read-only integration |
| Needed for | Passive state reading (temps, probe, mode) | Sending commands (set temp, start cook) |

## Advertisement decoding — SOLVED

### Call chain

```
extProcessBTData (0x10ae40)
  -> grill registry lookup (matches by MAC/UUID)
  -> FUN_00230460           ; whitening + AES-256 transform (per AD-structure half)
  -> FUN_0022f11c           ; "parse_grill_and_probe_status" — plain bit-field parser
       -> FUN_0023085c      ; LSB-first bitstream reader (NOT crypto)
```

`FUN_00230460` is the actual crypto step. It is **not** a simple stream
cipher: it applies a position-dependent add+XOR whitening pass (seeded by a
checksum over the input, static constant tables baked into the `.so`) and
then calls `FUN_00231934`, which is a real **fixslice AES-256** core (the
same optimized bitsliced implementation used by the Rust `aes` crate,
confirmed by matching round-function structure against
`aes-0.8.4/src/soft/fixslice64.rs`).

**Important calling-convention detail:** `FUN_00230460` must be called ONCE
PER RAW AD-STRUCTURE PAYLOAD HALF (a 20-byte and a 23-byte manufacturer-data
payload, at offsets `0xb` and `0x27` of the raw ~62-byte advert), not on the
43-byte concatenated buffer — it validates the input length is in range
`0x11..0x1f` (17-31 decimal) and returns an error sentinel outside that
range.

### Verification

Decoded a real captured advertisement (company ID `0x0C4F`) and confirmed
correctness two independent ways:

1. The decoded buffer's byte `0x13` = `0x34` (ASCII `'4'`) and last byte =
   `0x21` (ASCII `'!'`) — exactly the two sanity-check markers the real
   parser (`FUN_0022f11c`) itself validates before trusting the buffer.
2. Bytes 20-25 of the decoded buffer are the grill's real MAC address, in
   the clear (not reproduced here — never commit real device MAC addresses,
   see `CLAUDE.md`). Independently re-derived via a from-scratch Python port
   of the bit-field reader (`tools/decode_advert_fields.py`) applied to the
   same decoded bytes — two unrelated code paths landing on the identical
   MAC address is strong confirmation the whole pipeline is correct.

### Full bit-field layout (344 bits = 43 bytes, zero slack)

Field read order (not a flat table — the real control flow reuses width
groups):

1. **21 header fields**, widths (bits) `8,8,5,4,5,7,1,2,7,1,1,1,1,17,10,10,10,6,16,8,32` (160 bits).
2. **6× 8-bit fields** — the device's MAC address (48 bits).
3. **1× 8-bit field** — one more byte immediately after the MAC (semantics unknown).
4. **2× probe blocks**, each 9 fields with widths `3,1,1,3,4,4,5,10,17` (48 bits/probe,
   96 bits total) — matches the two physical probes (`probe1`/`probe2`) documented
   in `CLAUDE.md`.
5. **1 final 32-bit field.**

Total: 160 + 48 + 8 + 96 + 32 = 344 bits, exactly 43 bytes — a strong
structural check that this decomposition is correct (an earlier, wrong
transcription of this table also happened to sum to 344 bits by
coincidence of the same numbers in the wrong grouping; this version is
verified against the actual decompiled control flow, not just a bit-count
coincidence).

Field **semantics** (which field is target temp, current temp, cook mode,
etc.) are being mapped via live captures correlated against known grill/app
state changes (idle vs cooking, probe states, etc.) — see
`tools/live_decode.py`, a continuous passive BLE scanner (no phone/app
needed) that decodes and prints each new state in real time for this
purpose.

### Header field mapping (confirmed so far, HEADER_WIDTHS indices)

Confirmed by correlating live captures against a real cook session (target
temp changed from 40 to 45 in the app while `tools/live_decode.py` was
running):

| Index | Meaning | Evidence |
| --- | --- | --- |
| 13 | Cook time **remaining**, in seconds | Counted down steadily in real time (e.g. 21513 -> 21469 over 44 real-world seconds); cross-checked against the app's displayed remaining time (~5h56m) at `21600 - elapsed = 21469` (5h57m49s) — within ~2 min, consistent with the app rounding its display to whole minutes. |
| 14 | Live temperature reading (probably grill/oven temp) | Small continuous fluctuation (91-96) consistent with real sensor noise, unlike the fixed setpoint fields. |
| 15 | **Probe 1 live temperature**, whole degrees Celsius (no scaling) | Constant `18` for the entire session while the probe sat at room temp (matched the user's own app reading of "18°C"). Confirmed dynamically: rose to `25` then settled `24`, `23` when the user held the probe tip in their palm, tracking real-world hand-contact warming/cooling exactly. **Not** in the `probes[]` sub-block — despite being physically a probe reading, it's encoded directly in the header. |
| 18 | Cook time **set/total**, in seconds | Constant `21600` (= 6h00m) throughout the whole session — matches `field[13]` counting down from it. |
| 19 | **Target/set temperature**, whole degrees (no scaling) | Flipped from `40` to `45` at the exact moment the user changed the app's target temp from 40°C to 45°C. |

**Cook mode — field 3 (revised, second correction):** an earlier version of
this doc guessed field 2, then briefly fields 3+4 jointly. A third real mode
change (Dehydrate -> Smoke @ 120°C/2h04m -> Grill w/ probe1 target 75°C)
resolves it: field 3 alone matches `CLAUDE.md`'s documented `cookMode` enum
order (`NotSet, Grill, AirCrisp, Roast, Bake, Broil, Smoke, Dehydrate,
MaxRoast, SlowCook`) on BOTH confirmed endpoints — `7` during Dehydrate
(index 7) and `1` during Grill (index 1). The one earlier "Smoke=`2`"
reading doesn't fit this enum (Smoke would be index 6) and is most likely a
transient mid-navigation UI state captured while the user was still
scrolling the app's mode picker, not committed Smoke mode. Field 2 stayed
constant at `7` across every mode tested so far (Dehydrate, Smoke-setup,
Grill) — clearly NOT mode-related, real meaning still unknown. Field 4 and
field 6 also still unconfirmed.

**Fields 7 and 9 — new observation, cookType-related (tentative).** Comparing
the same live capture: during Dehydrate/Smoke (both plain timed cooks, no
probe target), `header[7]=0` and `header[9]=0`. Once switched to Grill with
a probe1 target of 75°C, both flipped to `header[7]=1` and `header[9]=1`.
Plausible reading: one or both encode **cookType** (Timed vs Probe) at the
header level, separate from the per-probe `probes[2]`/`probes[4]` flags
noted below — but since both fields changed together in this single test,
they aren't yet independently distinguished from each other. Needs a
Timed-cook-without-probe-target vs. Probe-cook contrast on a mode that isn't
also a mode change (to rule out mode-correlation instead of cookType).

**Probe fields — now well understood.** Tested with a probe-target cook
(Grill, probe1 target 75°C): `probes[0]` went from the idle baseline
`[0,1,0,0,0,0,0,0,0]` to `[0,1,1,0,1,0,0,75,0]`. This gives:

| `probes[]` index | Meaning | Evidence |
| --- | --- | --- |
| 1 | Probe **plugged in** flag | Constant `1` all session (user confirmed probe physically connected throughout) — not yet contrast-tested against physically unplugging it. |
| 2 | Probe **target-temp-is-set** flag (or "probe cook active") | `0` during plain timed cooks (Dehydrate/Smoke, no probe target set), `1` once a probe target temp was configured (Grill w/ 75°C target). |
| 4 | Related active/armed flag (co-varies with index 2) | Same `0`->`1` transition as index 2 in this test — not yet independently distinguished; could be a second bit of the same conceptual state (e.g. "target set" vs "actively tracking toward target"). |
| 7 (10-bit field) | Probe **target temperature**, whole degrees Celsius | Exactly `75` — matches the user's set probe1 target of 75°C precisely. |

Index 15's earlier finding (probe1's *live/current* temperature reading
lives in the **header**, not in `probes[]`) still stands — `probes[]`
appears to be specifically about the *target*/armed state, while current
readings are reported via the header fields instead.

**Preheat-related fields — partially observed, not yet nailed down.**
During Grill-mode preheating (before pressing "skip preheating" at ~1%
progress): `header[13]=600`, `header[18]=100`. Immediately after skipping:
`header[13]=60`, `header[18]=23`, `header[17]` flipped `0`->`1`. Plausible
reading: `header[18]` may be a preheat-related estimate/progress value (100
-> lower after skip) and `header[17]` an "actively cooking"/"preheat
skipped" flag, but this needs a CLEAN preheat-to-completion observation
(0% -> 100% without skipping) to confirm rather than guess from a single
skip event. `header[19]` read `8` during this Grill+probe session, NOT a
literal oven temperature — the app only showed a qualitative "grill temp
hoog" (high) setting here, no explicit numeric target, suggesting
`header[19]` may encode a **heat-level preset** (e.g. 1-10 scale) rather
than literal degrees when no explicit numeric grill temperature is set —
context-dependent on cook type, needs more testing to confirm.

Still unmapped: the `extra_byte` after the MAC, and the final 32-bit field
(changes every single advertisement, even with the same header — likely a
rolling counter, sequence number, or short-term nonce/checksum, not
app-visible state).

## GATT session key — unsolved, lower priority

`extSendBTPayload {"cmd":"Connect"}` triggers a fresh handshake; the
resulting session key lives only in the library's internal Rust state,
never persisted to disk on the phone (confirmed via full filesystem +
MMKV-store dump — see repo history for `frida_dump_storage.js` /
`frida_mmkv_key.js` findings). Decrypting/encrypting GATT indications
(`extDecryptData`/`extEncryptData`) only works after a live `Connect`
handshake for that specific session.

**Confirmed NOT a cloud dependency either:** blocking the backend
(`ads-eu.aylanetworks.com`, this product's white-label IoT cloud vendor —
see "Cloud architecture" below) via DNS makes the official app refuse to
even attempt BLE (zero native BLE calls fire), but this is an app-side
business-logic gate, not a requirement of the grill's protocol — the app
simply chooses not to try without cloud reachability. A from-scratch
integration is not bound by that choice.

Out of scope for a read-only passive-monitoring integration (which only
needs the advert channel, now solved). Would need to be solved separately
to support sending commands (temperature changes, starting a cook, etc.).

### ⛔ SHOWSTOPPER (2026-07-03): cloud control does NOT fit this project

**The cloud-control finding below is real and verified, but it CANNOT serve
this project's use case.** Core design constraint (from the user, restated):
**the grill is never connected to the internet — that is the entire point.**

Cloud commands only reach the grill when **the grill itself** polls the Ayla
cloud over its own WiFi. An offline grill never polls, so a command written to
the cloud (even the verified `201 Created`) is **queued forever and never
delivered**. HA having internet does not help: the broken link is cloud →
grill, which requires the *grill's* internet — which by design does not exist.
(The test grill's `connection_status` was `Offline`, last cloud-connected
2026-05-08 — consistent with this.)

**Consequence:** the only channel that reaches an offline grill is **local
BLE** — i.e. the GATT-write path, whose per-session encryption is (per the
analysis below) not derivable offline. So:
- **Read-only monitoring:** solved, local, shipped. ✅
- **Local command sending:** blocked on the unsolved GATT-write session key.
- **Cloud command sending:** technically works end-to-end (proven), but is
  useless for an air-gapped grill; only relevant to users who DO put their
  grill on WiFi.

The Ayla cloud path is retained below as verified reference (and as an optional
future feature for internet-connected grills), but it is **not a solution for
the local-first goal.**

**Clarified (2026-07-03, final): the app's cloud requirement is a GATE, not a
grill requirement.** The user confirmed (earlier DNS-block test): blocking the
Ayla domain makes the official app refuse to connect to the grill at all — zero
native BLE calls fire. So the app *chooses* not to do local BLE without cloud
reachability (account/telemetry business logic). The grill's own protocol does
NOT need internet — it is fully controllable over local BLE. **A from-scratch HA
integration is not bound by the app's gate:** it can send BLE commands directly,
offline, no account. Therefore the ONLY blocker for fully-local control is the
GATT-write per-session key (below). Cloud is a dead end (offline grill never
polls it); local BLE is the real and worthwhile target.

---

### ⭐ (2026-07-03): control CAN be done via the AYLA CLOUD (for online grills only)

**The entire GATT-write reverse-engineering below is moot for control.** A
live Frida + logcat trace of the official app sending a real temperature
change (45 → 40 while cooking) proved the command does **NOT** go over BLE at
all — no `extSendBTPayload` / `extEncryptData` fires. It is sent as a
**plaintext Ayla cloud property write**:

- Cloud: **Ayla Networks**, EU env — `https://ads-eu.aylanetworks.com`
  (user API `https://user-field-eu.aylanetworks.com`). Auth: Okta/Auth0
  bearer (`https://logineu.sharkninja.com`) → Ayla session.
- Device is addressed by its Ayla DSN / `device_key` (value REDACTED — it is
  device-identifying; keep it out of the repo per "Nooit committen").
- **Command property:** `SET_Cook_Command` (`direction:input`,
  `read_only:false`, `key:748000358`). Observed payload shape for a temp
  change (values illustrative, DSN redacted):
  ```json
  {"id":<DSN>,"mode":"dehydrate","seconds set":21600,"temp":40,"smoke":0,"skip preheat":0}
  ```
- **State properties (read):** `GET_GrillState` (748000375), `GET_CookState`
  (748000377), `GET_ProbeState` (748000376) — full plaintext JSON with
  `temps` (grill/air/smoke/probe0_a…/main/ui), `io.lid open`, probe
  plugged-in/active/temp/progress, etc.
- App credentials (EU prod `app_id`/`app_secret`) are present in the app and
  in the captured logcat, but are **NOT committed** (credential boundary).
  They live only in local capture notes on the dev machine.

**Implication:** sending commands from HA is a **standard Ayla IoT cloud
integration** (HTTPS REST property writes, account-authenticated) — no BLE
session-key crypto needed. The BLE channel is read-only advertisements even
in the official app. Tradeoff: this is **cloud control (needs internet +
Ninja account)**, unlike the local read-only advert path. It is, however,
the way the official app itself does it, and vastly simpler than the (now
confirmed unnecessary) GATT-write crypto. Next step: prototype an Ayla
property write against the device DSN using the app credentials + an Ayla
user login (all kept local, never committed).

**Everything below about the GATT session key remains true but is now only of
academic interest** — the app never uses BLE-write for control, so we don't
need it.

#### VERIFIED END-TO-END (2026-07-03): cloud control works

`tools/ayla_cloud_prototype.py` proved the whole control path live against the
real account + grill:

- **Auth is Okta/Auth0, NOT direct Ayla login.** Direct
  `POST /users/sign_in.json` with email+password returns 401 (the account's
  password lives in Okta). The real flow, confirmed working: obtain an Okta
  `id_token` (JWT from `logineu.sharkninja.com`) → `POST {user_url}/api/v1/
  token_sign_in` `{"token", "app_id", "app_secret"}` → **200**, Ayla session
  (`expires_in=86400`).
- **Device discovery:** `GET {device_url}/apiv1/devices.json` → the grill
  (model `AY008MVL1`, name "Rookertje").
- **State read:** `GET .../dsns/<DSN>/properties.json` → all `GET_*` props
  (CookState, GrillState, ProbeState, …) in plaintext.
- **Command write CONFIRMED:** `POST .../properties/SET_Cook_Command/
  datapoints.json` `{"datapoint":{"value": "<cook-command json>"}}` → **201
  Created**; read-back shows the new temp landed. (The test grill had not been
  cloud-connected since 2026-05-08, so `connection_status:Offline` and the
  datapoint queues with `echo:false` until the grill next joins WiFi — but the
  cloud accepted and stored the command.)
- Writable command props: `SET_Cook_Command` (mode/temp/time/smoke),
  `SET_GrillPower`, `SET_CookSkipDirective`, `SET_Exec_Command` (+ factory/
  wifi/debug we will NOT expose).

**Auth model for the HA integration:** user does the Okta login (on
SharkNinja's page, password never touches HA) → HA gets an id_token → exchanges
for an Ayla session → stores only the (refresh) token, encrypted. Needs the
**grill on WiFi/cloud** for commands to actually reach the hardware; BLE stays
the local read-only path.

---

### GATT session-key attack progress (2026-07-03)

**Phase 1 (wire protocol) — DONE.** Captured a live handshake via btsnoop
(`captures/btsnoop-setcmd-last.log`, gitignored) and confirmed the exact
framing with `tools/analyze_ninja_handshake.py --mac 0ce5a3198052`:

- `W len=2` → handle 0x0017, value `02 00` (CCCD enable indications; session start)
- `I len=20` → handle 0x0016 (encrypted challenge, random per session)
- `W len=48` → handle 0x0011 (auth response + commands; always exactly 48B)
- further 20B indications / 48B writes follow

Every app→grill write is **exactly 48 bytes**, every grill→app indication
**exactly 20 bytes** — no length variation. 48 = likely 16B IV/nonce + 32B
ciphertext (or 3× AES blocks). All ciphertext; btsnoop alone reveals no
plaintext.

**Phase 2 (live Frida trace) — BLOCKED (app instability).** The
Gadget-patched app (`~/ninja_patched_aligned.apk`, objection-injected,
NINJA-keystore signed) *can* be attached to: `tools/frida_hook_gatt_session.js`
resolves all six BTManager crypto exports live (`extEncryptData`,
`extDecryptData[WithOptionalKey]`, `extProcessBTData`, `extSendBTPayload`).
BUT: sending a temperature change does **not dispatch** — not even
`extSendBTPayload` fires — and the app crashes on grill reconnect. Cloud
reachability confirmed fine (pings `ingress-eufield.aylanetworks.com`), so
it is NOT the cloud gate. Conclusion: the repackaged Gadget build is fine
for passive inspection but too unstable to drive the live *control* path.
Next option if revisited: `frida -U -f` spawn-inject the STOCK app with an
early anti-detection bypass, instead of attaching to the Gadget build.

**Phase 3 (offline emulator replay) — IN PROGRESS, most stable route.**
`tools/replay_gatt_handshake.py` replays the captured challenge through the
real `.so` in Unicorn. The emulator exposes `process_bt_data`,
`decrypt_data`, `encrypt_data[_with_key]`, and — purpose-built for this —
`set_random_replay()` to feed deterministic entropy to `getrandom()` so a
captured session's derived key can be reproduced offline. Current state:
all session calls return `None` with `INVALID MEM access` faults during
setup. Two concrete bugs to fix next session:
  1. **JNI arg order:** `_jni_call` passes `[env, this, uuid_handle,
     data_handle]`, but the real signature is `(data: ByteArray, uuid:
     String)` → data and uuid are likely swapped for encrypt/decrypt.
  2. **Session init:** the session path needs prior init/registration
     (the advert `decode_advert` path is self-contained and works; the
     session registry path is unvalidated scaffolding — never run
     successfully before).
Once those are fixed: feed challenge → `process_bt_data`, then check whether
`decrypt_data(indication)` yields structured plaintext. If yes, the session
key is derivable offline (with `set_random_replay` for app entropy) and GATT
is crackable without a live phone. If it needs live BLE I/O the emulator
can't fake, fall back to Phase 2 spawn-inject.

#### Update (2026-07-03, later): bug 1 fixed, root blocker localized

**Bug 1 (JNI arg order) — FIXED.** `_jni_call` swapped uuid/data; corrected
to `(env, this, data, uuid[, key])`, matching the confirmed `extProcessBTData`
decompile signature `(param_1=env, param_2=this, param_3=data, param_4=uuid,
param_5=type)`. After the fix, `decrypt_data(indication)` no longer returns
None — it returns 84 bytes. **BUT** those 84 bytes are uninitialised emulator
memory (little-endian pointers like `b8fe1f01`=0x011ffeb8, `a0bc3d00`), NOT
plaintext — the decrypt ran but found **no session key** for the uuid.

**Root blocker — precisely localized:** the session/GATT path needs a
**per-device session registered in the Rust session registry (a global
HashMap keyed by uuid)**, which only gets populated by the app's live
`Connect` handshake. The emulator's `_call_sdk_init` calls `GrillCoreSDK.init`
with empty/null args (enough for the stateless advert leaf-function, which is
why `decode_advert` works), but never performs a device `Connect`, so the
registry is empty. `extProcessBTData(challenge)` returns None because
`FUN_00217ea4(&ctx, env, uuid)` (the by-uuid session lookup, seen at the top
of the decompile) finds no entry; `decrypt_data` then reads a garbage/empty
slot. The `INVALID MEM` faults (fva `0x12cefc`, `0x345dbc`, `0x185a0`,
`0x7b5c`) are in Rust allocator/TLS/global-init runtime paths hit when the
session code tries to touch that missing global state.

**Next concrete step (the real crux):** reverse `FUN_00217ea4` + the
`Connect` codepath to find the function that *creates* a session entry, then
either (a) call it directly to register a session for the uuid, or (b) drive
`extProcessBTData` with a proper `Connect`-type packet (not just the raw
challenge) so the native code allocates the session itself — feeding
`set_random_replay()` the app-side entropy so the derived key matches the
captured session. This is an open-ended RE dive into the Rust session
machinery; success is likely but not guaranteed. If it stalls, Phase 2
spawn-inject of the STOCK app remains the fallback.

#### Update (2026-07-03, latest): OFFLINE EMULATION IS A DEAD END — the GATT path is async

Traced `extProcessBTData`'s exact call path in the emulator (BL tracer): it
runs 8 calls then faults at fva `0x12cef8` with a null-deref while
**formatting a Rust panic**. The panic string (read from the `.so` at the
constant the faulting code loads) is:

> `"tried to use async function in non async context"`

This reframes the whole blocker. It is NOT merely a missing HashMap entry —
**the entire GATT session/crypto path is built on a Rust async runtime
(tokio).** String scan of the `.so`: `runtime`×51, `async`×46, `await`×8,
`spawn`×7, `tokio`×7, `waker`×6, plus `block_on`, `reactor`, `mpsc`,
`executor`. `extProcessBTData`, `extEncryptData`, and even the
`extDecryptDataWithOptionalKey` "bypass" path all route through this async
machinery (all call the same `FUN_003c3ba0` session lookup). Empirical
confirmation: `decrypt_data_with_key` fed three different explicit keys
(zeros-16, zeros-32, `11`×32) returned the **same** pointer-filled garbage
each time — it is NOT doing AES-with-the-given-key; it returns uninitialised
buffers because it never reaches the cipher, dying in the async/session
layer first.

**Conclusion:** unlike the advert crypto (a pure synchronous leaf function —
`FUN_00230460`, no globals, no async — which is exactly why the pure-Python
port + emulator oracle both work), the GATT command crypto is entangled with
a live tokio executor + reactor that expects real BLE socket I/O and driven
wakers. The Unicorn emulator can call synchronous leaf functions but cannot
run the async runtime, so **the offline-replay approach (Phase 3) cannot
reach the session key.** `replay_gatt_handshake.py` and the emulator session
calls are retained as evidence but are a dead end for key recovery.

**Remaining viable routes for GATT control (both need a live device):**
1. **Frida spawn-inject the STOCK app** (Phase 2, revisited) with early
   instrumentation + anti-detection bypass, hooking the crypto exports at the
   moment a real command is sent — capturing plaintext↔ciphertext↔key from
   the live async runtime while it actually runs. The earlier attach-based
   attempt failed only because the Gadget build was too unstable to send a
   command; `frida -U -f` spawn of the unmodified app avoids the repackaging.
2. **Hook the app's own session key in memory** once, live, then feed it to
   `extDecryptDataWithOptionalKey` — but since that path is also async, the
   key must be *used* live too; simplest is to just read plaintext directly
   from the app at the JNI boundary via Frida.

Net: sending commands requires a live, Frida-instrumented session on the
phone — it is not derivable purely offline. Read-only monitoring (the
shipped integration) is unaffected and complete.

## Cloud architecture (context only, not a shortcut)

The grill is registered on **Ayla Networks'** white-label IoT cloud
(`ads-eu.aylanetworks.com`, model `AY008MVL1`), alongside standard Auth0
OAuth for the user account. This explains the mandatory account creation,
but is **not** a shortcut for the local crypto: Ayla's own documented BLE
stack (`AylaBLEDevice`, a fixed "Ayla GATT Service" with characteristics
like `GATT_CHAR_DUID`) does not match what this grill actually exposes
(service `0000fcbb`, custom `extProcessBTData`/`extDecryptData` native
functions) — SharkNinja built its own local BLE transport+crypto on top of
Ayla's cloud backend, not Ayla's mobile BLE SDK.

## Pure-Python port — DONE (2026-07-02)

Full pure-Python port of the advert-half decryption is complete and
verified byte-for-byte against the real native code. Implementation:
`tools/advert_crypto_port.py` (`decode_advert_half(raw: bytes) -> bytes`,
uses only `pycryptodome`, no `.so`/emulator needed at runtime).

### What the earlier (2026-07-01) attempt got wrong

The previous pass correctly identified that `FUN_00230460` calls into
`FUN_002309ac`, which builds a table of 6 "rows" (each an AES-256
key + 128-bit IV pair) via a checksum + whitening pass over the raw
input, feeding a **fixslice AES-256 core** (`FUN_00231934`, confirmed
by matching `FUN_00213f44`'s round function and `FUN_00214724`'s
bit-permutation structure against RustCrypto's `aes` crate
`fixslice64.rs`). That part of the trace was correct. What it got
wrong: it assumed this whitened/derived row material was *itself*
used as the key for decrypting the actual advert bytes. It is not —
those 6 rows only exist to prepare **encrypted constants
(`__ptr_02`/`__ptr_03`) that get thrown away**; row 0 of that table
(and, separately, row 5) are just the literal static constants
`__ptr_00`/`__ptr_01`, unmodified. The advert bytes themselves are
decrypted using **row 0 directly** (i.e. the static constants), via a
*different* function, `FUN_002315a0` — not `FUN_00231934` at all, and
not any input-derived key.

This was discovered by instrumenting the Unicorn emulator with code
hooks at `FUN_00231934`'s and `FUN_002315a0`'s entry points and
dumping their actual x0-x3 argument slices for a real
`_decode_advert_half()` call: `FUN_00231934` is called only from
inside `FUN_002309ac` (10 times, always with `__ptr_02`/`__ptr_03` as
the "plaintext" argument — dead-end busywork for this codepath), while
`FUN_002315a0` is called exactly twice per advert half, always with
the *same static* 32-byte key and 16-byte IV.

### The verified algorithm

Static constants (32-byte AES-256 key, 16-byte IV), recovered from the
row-0 literal assignments in `FUN_002309ac`
(`tools/artifacts/ghidra_decompiled_rebuild.txt` lines ~681-684 and
697-698) and cross-checked byte-for-byte via direct emulator calls
into `FUN_002315a0`:

```
KEY_CONST = eb08bb107cb293618536fd3dee1d2f6cdbc3d888bfac8f53839704220f1f197e   # 32 bytes
IV_CONST  = 539ca281078468fd901e591ae1be425b                                   # 16 bytes
```

(Note: an earlier draft of this doc/`tools/advert_crypto_port.py` had
both constants **truncated by exactly one trailing byte** — a
copy-paste artifact — which is why the "block 0" hypothesis back then
only matched the first 4 output bytes of each vector: a 31-byte key
still produces *some* AES output, just wrong beyond the point the
missing key byte starts to matter in the key schedule. Always verify
these by re-reading the qword literals from the decompile directly,
not by trusting a previously-recorded hex string.)

For a raw advert half `raw` of length `n` (17-31 bytes, i.e. one
16-byte block + a 1-15 byte tail):

1. `out0 = AES-256-CBC-Decrypt(KEY_CONST, IV_CONST, raw[0:16])` — a
   single 16-byte block, so equivalent to
   `AES-256-ECB-Decrypt(KEY_CONST, raw[0:16]) XOR IV_CONST`.
2. `tail_len = n - 16` (1-15).
3. Build a second 16-byte block: `window = out0[tail_len:16] +
   raw[16:n]` — the last `16 - tail_len` bytes of `out0`, followed by
   all `tail_len` raw tail bytes.
4. `out1 = AES-256-CBC-Decrypt(KEY_CONST, IV_CONST, window)` — same
   fixed key/IV, a **fresh** single-block decrypt (not chained from
   step 1's output as an IV — both calls independently use the same
   static `IV_CONST`).
5. Final output = `out0[0:tail_len] + out1` — exactly
   `tail_len + 16 == n` bytes.

Both AES calls share the identical static key/IV — there is no
per-message or input-derived key material anywhere in this path. The
two-call "telescoping" structure exists purely because the underlying
cipher only natively processes 16-byte blocks, but the real
manufacturer-data payload lengths (20 and 23 bytes observed in
practice) aren't block-aligned; the tail gets folded into a second
block built from the otherwise-unused tail of the first block's
decrypted output.

### Verification

- All 7 hand-recorded test vectors (4× 20-byte, 3× 23-byte) match
  exactly.
- An additional 150 randomly generated vectors, covering every valid
  length from 17 to 31 bytes (10 trials each), all match exactly
  against the real native implementation (verified live via
  `tools/grillcore_emu.py` calling `FUN_00230460` directly as the
  oracle).
- `tools/advert_crypto_port.py`'s embedded `__main__` self-test
  reproduces the 7 core vectors with **no dependency on the `.so` or
  the emulator** — safe to ship to end users as the production decode
  path.

### Still open (minor, non-blocking)

- The exact bit-level reason `FUN_00231934`'s row-building machinery
  exists at all (it's computed but never consulted for anything that
  affects the final advert output) isn't understood — possibly dead
  code left over from a more general internal crypto abstraction
  shared with the (still-unsolved) GATT session-key path, or possibly
  it *is* consulted somewhere for a code path not exercised by
  advert decoding specifically (e.g. GATT). Not required to finish
  the advert port; noted here only for completeness in case it's ever
  relevant to the separate GATT session-key investigation.

## Distribution: emulator is a dev tool only, NOT shipped

`tools/grillcore_emu.py` is a Unicorn AArch64 emulator that loads the real
`.so` and can call its internal functions directly (`decode_advert()`,
`encrypt_data()`, `decrypt_data()`, etc.) — extremely useful for verifying
reverse-engineering work quickly and correctly, since it runs the *actual*
Rust/AES code instead of a hand-ported reimplementation.

**However, per `CLAUDE.md`, `libgrillcore_android.so` may never be
committed and cannot be redistributed to end users.** The emulator was
used as a **reverse-engineering oracle only**, to verify the
from-scratch pure-Python port of the advert crypto
(`tools/advert_crypto_port.py`, see above — now DONE and verified)
byte-for-byte; only that pure-Python module should be wired into
`custom_components/ninja_woodfire/` — never the emulator or the `.so`
itself.

## Tooling

All RE tooling lives in `tools/`:

- `elf_analyze.py`, `elf_symbols.py`, `disasm_func.py` — static ELF/capstone analysis.
- `grillcore_emu.py` — Unicorn AArch64 emulator (dev-only oracle, see above).
- `decode_advert_fields.py` — pure-Python bit-field reader + verified width table.
- `verify_decode_advert.py` — end-to-end regression test against a known-good sample.
- `frida_*.js` + `frida_run.py` — live device hooks (native-level; this app's Gadget
  build blocks the Java bridge, so hooks must attach directly to native exports,
  see comments in `frida_hook_btmanager.js` / `frida_ssl_native_dump.js`).
- `ghidra_decompile_*.py` — Ghidra headless post-scripts (Jython, run via
  `analyzeHeadless -postScript`).

Your own extracted `.so` goes in `tools/artifacts/extracted/lib/arm64-v8a/`
(gitignored, never committed).
