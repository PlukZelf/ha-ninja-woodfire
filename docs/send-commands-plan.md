# Plan: Sending Commands to the Grill from Home Assistant

**Goal:** let HA *write settings* (set temp, start/stop cook, timer, etc.) to the
grill over **local BLE**, pure Python, no phone and no cloud at runtime.

**The one and only blocker:** the GATT command channel is encrypted with a
**per-session key** established by a `Connect` handshake. Reading state is already
solved via advertisements and shipped — this plan is exclusively about the
**write/control** path.

This document is the execution plan. It is phased, and **each phase has a
validation gate** so a worker (including a cheaper agent) knows when a phase is
correct and can stop. Do phases in order; do not skip a gate.

---

## 0. What we already have (inventory — read before starting)

**Confirmed protocol facts**
- **Command format is plain JSON** (captured via `extSendBTPayload`):
  `{"cmd":"<Command>","id":"<MAC>","data":[…],"key":<null|…>}`
  e.g. `{"cmd":"Connect",…,"key":null}` starts a session; `SetTemp`/`SetCookTime`
  etc. carry values in `data`. The app hands grillcore this JSON; grillcore does
  the handshake + encryption + BLE write internally.
- **Wire framing** (from live btsnoop, confirmed by `tools/analyze_ninja_handshake.py`):
  1. `W len=2` → handle **0x0017**, value `02 00` (CCCD: enable indications = session start)
  2. `I len=20` → handle **0x0016** (encrypted **challenge**, random per session)
  3. `W len=48` → handle **0x0011** (**auth response**, then commands; always 48B)
  4. further 20B indications / 48B writes follow
- **GATT layout** (confirmed from laptop, service `fcbb`):
  `b001` read `0x000d` · `b002` write(+w/o-rsp) `0x0010` · `b003` notify `0x0012` · `b004` indicate `0x0015`
- **State stream:** grill pushes 64B encrypted state on `b004`; `b001` readable on
  demand (64B); **every read differs for constant state → per-message nonce/IV.**

**Confirmed crypto facts (narrow the search)**
- Key is **per-session** (3 independent confirmations: changing nonce, runtime
  vtable dispatch `blr [session+0x558]`, tokio-async entanglement). **No static key.**
- AES is **Rust-inlined fixslice** — **NOT** system `libcrypto`/BoringSSL (hooked
  20 libcrypto entry points during a live decrypt → **zero** fired).
- The raw key is **bitsliced** in memory (round-keys), so scanning memory for a
  contiguous 32-byte key **does not work**. The raw key only exists momentarily as
  the **input argument to the AES key-schedule** (`Aes256::new(&[u8;32])`).
- The command-encrypt is an **internal (non-JNI) path** — `extEncryptData` never
  fires for a temp change; only `extSendBTPayload` (the JSON) does.
- **Offline emulator replay is a dead end** (`replay_gatt_handshake.py`): the GATT
  path runs on a tokio async runtime the Unicorn emulator can't drive
  (`"async function in non async context"`). Do not reinvest there.

**Capability facts (what works)**
- **A from-scratch client reaches the grill.** `bleak` on the dev PC connects,
  and the grill streams `b004` — no app, no cloud, no account.
- **A stable central holds the connection** (laptop held 40s+ solid). Flakiness
  was only the *repackaged phone app*, never the grill/BLE. Grill GATT
  connections are **transient** (open on activity, then drop) — that's fine; the
  client model is connect → handshake → send → disconnect.
- **Passive JNI-boundary capture works** (thin, attach-FIRST-then-connect Frida
  hook): we captured the b004 state **plaintext** and the command **JSON** live,
  in-context, with no async abort — because we only *observe* the app decrypting.

**Ground-truth artifacts (validation oracles — preserve these)**
- `scratchpad/gatt_capture_1.txt` — a b004 `(cipher 64B → plaintext 47B)` state pair.
- `scratchpad/gatt_capture_2.txt` — a real `extSendBTPayload` command JSON.
- `scratchpad/laptop_b004_capture.txt` — laptop connection + per-session verdict + static notes.
- **Advert key/IV** (the correctness beacon for any AES hook — if a hook is on the
  right function and adverts flow, it must show this):
  key `eb08bb107cb293618536fd3dee1d2f6cdbc3d888bfac8f53839704220f1f197e`,
  iv `539ca281078468fd901e591ae1be425b`.

**Existing tooling (reuse, don't rewrite)**
- `tools/analyze_ninja_handshake.py` — parse a btsnoop into the handshake frames.
- `tools/grill_gatt_probe.py` — bleak connect/observe (read-only probe).
- `tools/parse_btsnoop_att.py`, `tools/capture_btsnoop.sh` — capture/parse.
- `tools/elf_analyze.py` / `tools/disasm_func.py` — capstone disasm of the `.so`
  (set `NINJA_SO_PATH`; addresses are app-mapped, i.e. `.so` vaddr).
- `tools/frida_hook_*.js`, `tools/frida_run.py` — Frida harnesses.
- Scratchpad (this session) has the **working** thin/attach-first hook pattern:
  `probe_attach.py`, `hold_and_capture.py`, `key_capture_v2.py`, `stalker2.py`.

**Key `.so` addresses (app-mapped)**
- `extProcessBTData` `0x10ae40` · `extSendBTPayload` `0x10afd4` · `extDecryptData` `0x10401c`
- real decrypt `FUN_003c3ba0` `0x2c3ba0` → per-session dispatch `blr x22` at `0x2c3cf4`,
  where `x22 = [session+0x558]`; incoming router `FUN_002aa168` `0x2aa168`.

---

## Strategy

We **cannot** avoid reversing the per-session math (a captured key is useless next
session). But we **can** make it tractable: **capture (challenge → key) pairs live**
via a passive hook on the AES key-schedule, then reverse the small deterministic
function `key = f(challenge, static_secret)` with the pairs as ground truth. Every
later phase is **validatable offline** against captured pairs, so only Phases 1 and
the capture tasks need the phone.

Route chosen: **Frida-assisted empirical capture → reverse the derivation →
reimplement in Python → validate offline → build the client → port to HA.**

**Prerequisite (Phase 0):** a *stable* instrumentation setup, because the current
Gadget instance degrades after ~5–7 attach cycles. Either reinstall the Gadget
build fresh, or set up `frida -U -f` spawn-inject of the **stock** app with an
anti-detection bypass (`tools/bypass_frida_detection.sh` exists as a starting point).

---

## Phase 0 — Consolidate the mess & get a stable rig
**Objective:** one clean working area and a reliable capture harness, so later
phases aren't fighting scattered scripts and a dying app.

**Tasks**
- 0.1 Create `tools/gatt_send/` and move the *working* patterns there as named,
  documented tools: `attach.py` (resume-off-logo + hold), `capture.py` (thin
  attach-first JNI hook), `btsnoop.py` (wrap the existing parser). Delete/retire
  dead scratch scripts.
- 0.2 Preserve the ground-truth pairs into `captures/` (gitignored) as canonical
  fixtures the offline validators load. **Redact MAC/device-serial** from anything
  that could be committed.
- 0.3 Establish a **stable instrumentation rig**: prefer a *fresh reinstall* of the
  Gadget build; document the exact launch+attach sequence that reaches past the
  logo and stays live. If the Gadget keeps degrading, stand up stock-app
  spawn-inject instead. Write the procedure in `tools/gatt_send/README.md`.

**Deliverable:** `tools/gatt_send/` with a documented, repeatable capture rig and
preserved fixtures.
**Gate:** from a cold start you can launch the app, attach a thin hook, and see the
live advert plaintext (or `extProcessBTData` firing) **twice in a row** without the
app crashing.

---

## Phase 1 — Reliable session-key capture (the linchpin)
**Objective:** for a given live session, capture `(challenge_20B, session_key_32B)`
reproducibly. Everything downstream depends on this.

**Why it's possible:** the raw key is the **input arg to the AES key-schedule**
before bitslicing. We just need that function's address.

**Tasks**
- 1.1 **Find the key-schedule.** Stalker-trace ONE natural decrypt from
  `FUN_003c3ba0` (0x2c3ba0) across **all** modules (not just grillcore — the
  earlier trace showed the work leaves grillcore) to enumerate called functions;
  identify the AES-256 key-schedule (the fn that reads 32 bytes and writes the
  fixslice round-key schedule, ~0x1e0 bytes). Start from `tools/gatt_send/` +
  `stalker2.py` pattern. Cross-check statically with `disasm_func.py`.
- 1.2 **Hook it (freeze-safe).** Thin hook: record only the key-pointer arg
  (`x0`/`x1`) — no heavy work on the hot thread; do any dump off-thread via `rpc`.
- 1.3 **Validate the hook.** While adverts flow, the same/related AES path should
  expose the **known advert key** `eb08bb10…197e`. Seeing it = the hook is on the
  real key material. (If adverts use a different entry, validate by decrypting a
  captured b004 pair in Phase 3 instead.)
- 1.4 **Correlate the challenge.** Simultaneously hook `extProcessBTData`
  (0x10ae40) and log the 20-byte input (`data` arg is at **x3**) as the session's
  challenge. Emit `(challenge, key)` together per session.
- 1.5 Capture **≥3 sessions** (kill app / reconnect between each → fresh challenge+key).

**Deliverable:** `tools/gatt_send/capture_keys.py` → prints `(challenge_20B,
session_key_32B)` tuples; ≥3 saved to a gitignored fixture.
**Gate:** the advert key validates the hook **AND** you have ≥3 distinct
`(challenge, key)` pairs from 3 fresh sessions.

**Risk/fallback:** if the raw key never surfaces at the key-schedule, fall back to
**un-bitslicing**: locate the fixslice round-key region in the session struct and
invert the fixslice packing (deterministic transform) to recover the raw key.

---

## Phase 2 — Reverse the key derivation  `key = f(challenge, secret)`
**Objective:** a pure-Python `derive_key(challenge) -> key` that reproduces the
captured pairs, so HA can make its own session key.

**Tasks**
- 2.1 With the ≥3 `(challenge, key)` pairs, test standard constructions:
  `key = HKDF/HMAC-SHA256(secret, challenge)`, `SHA256(secret‖challenge)`,
  `AES(secret, challenge)`, truncations/concatenations. Brute the obvious shapes.
- 2.2 **Extract candidate static secrets** from the `.so`: the advert key/IV live
  in `.rodata`; the GATT secret(s) are likely nearby constant tables. Dump
  32/16-byte high-entropy constants near the handshake code and feed them to 2.1.
- 2.3 **Static-analyze the challenge consumer** to name the primitive: follow
  `extProcessBTData → FUN_002aa168 (0x2aa168)` and the `Connect` path from
  `extSendBTPayload (0x10afd4)` into the session-init that consumes the challenge;
  identify the KDF/cipher used (hash? HMAC? AES?). `disasm_func.py` + the fact that
  the AES core is fixslice (Rust `aes` crate) narrows the crate set.

**Deliverable:** `custom_components/.../gatt_crypto.py::derive_key(challenge)`
(dev copy under `tools/gatt_send/` first).
**Gate:** `derive_key` reproduces **all** captured `(challenge → key)` pairs exactly.

---

## Phase 3 — Reverse the record encryption (b002 write / b004 read)
**Objective:** with the key, `encrypt_record(plaintext, key, …) -> 48B` and
`decrypt_record(cipher, key) -> plaintext`, matching ground truth.

**Tasks**
- 3.1 **Decrypt direction first** (we have a b004 `cipher→plain` pair). Using the
  session key captured for *that* session, determine mode + IV/nonce placement:
  try `64B = [16B IV ‖ 48B CBC-ct]`, CTR/GCM with embedded nonce, etc., until
  `decrypt(cipher,key) == known plaintext`. The 47B plaintext = `0x0c` len + `&` +
  device-id + `0x25` state block + trailer.
- 3.2 **Encrypt direction.** Capture a command send tuple `(command_JSON,
  48B_ciphertext_written, session_key)` — add a thin hook on the **b002 GATT write**
  (system `writeCharacteristic` / the char-write native) to grab the exact 48B, and
  reuse the Phase-1 key. Determine the scheme so `encrypt(JSON,key,…) == 48B`.
- 3.3 Nail the **48B structure**: IV/nonce vs counter, ciphertext length, any
  MAC/tag, and how the per-message nonce is chosen (fixed-from-session? counter?
  random-prefixed?). The "different ciphertext every read" says the nonce is in the
  message or a counter — pin which.

**Deliverable:** `gatt_crypto.py::{encrypt_record, decrypt_record}`.
**Gate:** `decrypt_record` matches the captured b004 pair **and** `encrypt_record`
reproduces a captured 48B command write byte-for-byte.

---

## Phase 4 — Reverse the auth handshake (first 48B write)
**Objective:** `build_auth_response(challenge) -> 48B` so the grill accepts the
session (the first write after the challenge is auth, not a command).

**Tasks**
- 4.1 Capture `(challenge_20B, first_48B_auth_write, session_key)` for a session
  (b002-write hook + key hook + challenge hook together).
- 4.2 Determine how the auth write is built — likely
  `encrypt_record(proof(challenge), key)` where `proof` is a known transform of the
  challenge (echo, hash, or a fixed structure). Reuse Phase-3 `encrypt_record`.

**Deliverable:** `gatt_crypto.py::build_auth_response(challenge)`.
**Gate:** reproduces the captured first 48B auth write exactly.

---

## Phase 5 — Pure-Python client (end-to-end from the laptop)
**Objective:** a standalone `bleak` script performs the full flow with **no phone**:
connect → `CCCD 0x0017 ← 02 00` → receive 20B challenge → `derive_key` →
`build_auth_response` → write 48B (auth) → `encrypt_record(SetTemp JSON)` → write
48B (command) → observe the setting change.

**Tasks**
- 5.1 Assemble Phases 2–4 into `tools/gatt_send/ninja_client.py` on top of the
  `grill_gatt_probe.py` connection code. MAC from `NINJA_GRILL_MAC` (never hardcode).
- 5.2 Handle the transient-connection model (connect per command; short-lived).
- 5.3 Verify the change lands (via the app, the grill panel, or the advert state
  the HA integration already decodes).

**Deliverable:** `tools/gatt_send/ninja_client.py`.
**Gate:** **change the grill's temperature from the laptop**, confirmed
independently — the milestone that proves local control works.

---

## Phase 6 — HA integration (control entities)
**Objective:** expose control in HA using the pure-Python crypto from 2–4.

**Tasks**
- 6.1 Add a **connectable** GATT path (manifest `connectable: true` for the command
  flow; keep the passive advert reader for state). Use HA's `bluetooth`
  `async_ble_device_from_address` + `bleak-retry-connector`.
- 6.2 A **command coordinator**: on a control call, connect → handshake → send →
  disconnect (matches the grill's transient model). Serialize commands; back off on
  failure.
- 6.3 Add entities mapping to the JSON commands: `number` (target temp, timer),
  `select` (cook mode), `switch`/`button` (start/stop/power). One command schema
  per entity, values into `data`.
- 6.4 Reuse `gatt_crypto.py` (the vendored pure-Python module) — no `.so`, no phone.

**Deliverable:** control entities in the integration; docs + README updated;
`connectable: true` where needed.
**Gate:** set the grill temperature from the HA dashboard end-to-end.

---

## Dependency map & who-needs-the-phone
```
Phase 0 (rig)          ── phone (setup)
Phase 1 (key capture)  ── phone           ← LINCHPIN
Phase 2 (derive key)   ── offline (+.so)  ← validate vs Phase 1 pairs
Phase 3 (record enc)   ── phone once (b002 write capture) + offline validate
Phase 4 (auth)         ── phone once (auth write capture) + offline validate
Phase 5 (py client)    ── laptop + grill  ← proves control
Phase 6 (HA)           ── HA host
```
Phones only needed for the **capture** tasks (1, 3.2, 4.1). Everything else is
offline/validatable, so cheap agents can own Phases 2/5/6 and the offline halves of
3/4, gated by fixtures.

## Non-negotiables
- Never commit MAC / device serial / DSN / account creds / raw captures — see
  `CLAUDE.md`. Fixtures live in gitignored `captures/`.
- The grill is **air-gapped by design** — no cloud at runtime. Local BLE only.
- Don't reopen the offline-emulator route (async wall) or the libcrypto route
  (grillcore uses inlined Rust AES) — both are closed, documented above.

---

## Execution Protocol — how to stay on-plan (READ FIRST, applies to every worker)

The failure mode this section prevents: wandering off into interesting-but-
irrelevant work (re-solving *reading*, reopening closed routes, "improving" things
nobody asked for). The rules:

**R1 — One phase at a time.** A worker is assigned exactly **one** phase (or one
numbered task). It may not start the next phase. Finishing = producing the phase's
**Deliverable** and making its **Gate** pass — nothing more.

**R2 — The Gate is a runnable check, not an opinion.** Every phase's gate is a
script under `tools/gatt_send/checks/check_phaseN.py` that prints `PASS` or
`FAIL: <reason>` against the fixtures. "Done" means that script prints `PASS`. No
gate script yet → the worker's *first* job is to write it from the phase's Gate
line, get it reviewed, then satisfy it. Never self-certify with prose.

**R3 — STOP on block; do not improvise.** If a worker is blocked (can't hit the
gate, tool fails, hypothesis dead), it **stops and reports** in `STATUS.md` with:
what it tried, the exact failure, and the artifact it produced. It does **not**
invent a new strategy or wander into another phase. A human (or the planning model)
picks the next move.

**R4 — Respect the DO-NOT list** (closed routes — reopening them is off-plan):
  - ❌ Offline Unicorn emulator replay of the GATT path (tokio async wall).
  - ❌ Hooking system `libcrypto`/BoringSSL for the GATT key (grillcore uses
       inlined Rust AES; 20 hooks fired nothing).
  - ❌ Scanning memory for a contiguous 32-byte key (it's bitsliced).
  - ❌ Any work on the **read/advert** path — reading is DONE and shipped. This
       plan is *only* about writing/control.
  - ❌ Cloud / Ayla anything at runtime.

**R5 — Scope fence.** Touch only the files named in the assigned phase's
Deliverable (+ its check + `STATUS.md`). No drive-by refactors, no renames, no
"while I'm here" changes elsewhere.

**R6 — Update the ledger, always.** Before finishing (pass OR blocked), the worker
updates `docs/gatt_send_STATUS.md`: phase, state (`todo|in-progress|blocked|PASS`),
the gate result, deliverable path, and the single concrete **next task**.

### Per-worker task template (use this to dispatch a cheap agent)
```
ASSIGNMENT: Phase <N>, Task <N.x> ONLY.
READ FIRST: docs/send-commands-plan.md (Phase <N> + Execution Protocol) and
            docs/gatt_send_STATUS.md.
DO: <the one task>. Produce ONLY: <deliverable path>.
GATE: make tools/gatt_send/checks/check_phase<N>.py print PASS. Paste its output.
RULES: obey R1–R6. Do not start any other phase. Do not touch the read/advert path.
       Do not reopen the DO-NOT list. If blocked, STOP and write the blocker to
       docs/gatt_send_STATUS.md — do not improvise another approach.
DONE = gate prints PASS and STATUS.md is updated. Nothing else.
```

### Ledger seed (`docs/gatt_send_STATUS.md`)
Create it with one row per phase, all `todo` except what's already true, and the
current next task pointing at **Phase 0**. Every worker leaves it accurate on exit.

**Reviewer rule (for whoever dispatches workers):** accept a phase only if its
`check_phaseN.py` prints `PASS` on your machine against the fixtures, and the
worker touched only in-scope files. If either fails, bounce it — don't let "looks
right" through. Gates are the contract.
