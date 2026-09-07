# Measured, on real hardware, against the real ROM

**Everything else in `docs/ds/` is a design study written without a ROM or a working backend.
This file is measurement.** Where the two disagree, this file wins; where this file is silent,
the design studies are still the best available reasoning and are labelled honestly.

Date: 2026-09-07. Machine: Oracle Ampere Neoverse-N1, **2 shared cores**, no GPU.
ROM: `Pokemon - HeartGold Version (USA).nds`, sha1 `4fcded0e2713dc03929845de631d0932ea2b5a37`,
game code `IPKE`, internal name `POKEMON HG`.
Emulator: DeSmuME 0.9.12 via py-desmume 0.0.9, headless (`SDL_VIDEODRIVER=dummy`).

---

## 1. Throughput — the number that decides the project's shape

Measured off-air with `tools/bench_desmume.py` after a 300-frame warmup.

⚠️ **Read the three throughput rows as ONE noisy measurement, not three comparable ones.** The
memory row runs over **600** frames where the others use 1800, and it comes out *faster* than
raw emulation — impossible if the variants cleanly isolated their overheads. ⚠️ **And the
benchmark boots the ROM and measures the TITLE SEQUENCE**: it never loads a save, supplies no
input, and never reaches an overworld or a battle. These are first bounds, not a
characterisation of the workload a real environment or broadcast would run.

| | frames/s | vs realtime |
|---|---:|---:|
| emulate only | 66.3 | 1.11x |
| **emulate + read both screens** | **63.3** | **1.06x** |
| emulate + 40 memory reads | 67.2 | 1.12x |
| *Game Boy (PyBoy) env, same machine* | *2266* | *38x* |

**The DS is ~36x heavier per frame than the Game Boy environment.**

> ⚠️ This **supersedes the provisional note in `00-FEASIBILITY.md`**, which stated that its
> "approximately 38× realtime baseline ... come[s] from the task description" and was
> explicitly unverified. The 38x figure was right for the Game Boy. Nothing had measured the DS.

Two consequences, which are not the same consequence:

- **Training on a machine like this is impractical by a wide margin.** ⚠️ An earlier version of
  this file said *"structurally impossible"*; that was overstated and an adversarial review was
  right to reject it. 🔑 **Frames are the wrong denominator — agent DECISIONS are.** The Game Boy
  env takes one action per 24 frames, so 2266 fps is **94.4 decisions/s**. At the same repeat,
  63.3 fps is **~2.64 decisions/s**, and 10M transitions is roughly **44 days** of continuous
  compute before preprocessing, inference or training updates are added. That is a bad plan, not
  a physical impossibility — and the distinction matters, because "impossible" ends an
  investigation while "44 days" asks what budget exists. ⚠️ The DS action repeat is **not
  established**; 24 is Red's, assumed here for comparison only.
  **DS training still belongs on a desktop GPU machine.**
- **Broadcasting is possible, with ~6% headroom.** ⚠️ "No headroom" was also overstated: 63.3 fps
  against the DS's 59.826 is **5.8%**, about **0.9 ms of slack per frame**. Thin, not zero. The
  Game Boy stream is throttled *down* from 38x to ~2.5 steps/s and idles at ~2.6% of a core, so
  competing load is invisible there and is a real risk here. **Measure under real contention, on
  a gameplay save rather than the title screen, before scheduling a DS broadcast.**

### State save/load

| operation | median of 5 |
|---|---:|
| `savestate.save_file` | **70.5 ms** |
| `savestate.load_file` | **139.0 ms** |

Free on the Game Boy; not here. Every episode reset pays the load. This matters specifically
because save-state broadcast ("swarming") is the technique
[pokemonred_puffer](https://github.com/drubinstein/pokemonred_puffer) credits for finally beating
Red, and it is built entirely out of state loads.

---

## 2. 🚨 py-desmume's `keypad_add_key` / `keypad_rm_key` are unusable

**Do not call them.** `05-INPUT-AND-TOUCH.md` does not cover this; it is a real gap and it cost
most of a day.

Observed:

```
press("X")     keypad 4095 -> 3999
release("X")   keypad 3999 -> 2975     # does not return to where it started
```

Three facts, none wrong alone, that compose into the bug:

1. The setter is sound — `keypad_update(v)` then `keypad_get()` returns **exactly `v`**
   (verified directly).
2. A freshly constructed emulator's keypad reads **4095** — all twelve bits — because the DS
   register convention is **1 = RELEASED**.
3. `keypad_add_key` is a **read-modify-write**:
   `keypad_update(add_key(keypad_get(), key))`.

So the first press reads 4095, treats it as a *pressed* mask, and **holds every button on the
console down at once**; later calls compound it.

⚠️ **The symptom actively misleads.** The delta was **96**, nothing like the 1024 of a single
key's bit, which sent three separate investigations at the `keymask()` mapping — which was
correct throughout. 96 is `LEFT|UP`, dropped by the emulator's own **D-pad sanitisation**
because RIGHT and DOWN were also "held".

**Fix:** zero the pad at construction, hold the pressed-mask in your own code, call
`keypad_update()` directly, and **never read the register back** — it rewrites its own contents,
so a legitimate press can vanish from the value you read.

🔑 **General rule: never read-modify-write a register that sanitises itself.**

⚠️ **Why this belongs in a public doc:** it does not crash. An agent trained against it presses
the wrong controls forever, which presents as *"the model cannot learn"* — a diagnosis that
sends you to the reward function, the network and the hyperparameters, and never to the keypad.
Also provide a `release_all()` for `reset()`: a key left down across a reset is invisible in
every observation.

---

## 3. Memory — first live probe, and a correction to my own approach

`06-HGSS-MEMORY.md` is **right, better-sourced than the shortcut below, and should be preferred**.
It derives the model from the [pokeheartgold decompilation](https://github.com/pret/pokeheartgold):
save-backed state lives in a live `SaveData` allocation reached through the global
`sSaveDataPtr` ([src/save.c](https://github.com/pret/pokeheartgold/blob/master/src/save.c)).

The shortcut in service today uses the community/AR-code anchor `0x0211186C` with offsets
(trainer id `+0xD064`, party PID `+0xD088 + 0xEC*slot`) from
[Project Pokémon's HGSS AR code lists](https://projectpokemon.org/home/forums/topic/4828-pok%C3%A9mon-heartgold-and-soulsilver-ar-codes/).
That is **weaker provenance** — an AR address is specific to one title *and* one region, and
nothing in a ROM header says which list you hold.

### What the live probe found

Booted the real ROM, mashed A for **19,860 frames** (~100 s):

- The anchor **became valid at frame 180** and held **`0x0226F284`**, stable across **656
  samples, one distinct value**. So it is a real, early-populated pointer and the address is
  structurally right for this ROM.
- **Verification still failed, correctly**: with no save loaded, trainer id and every party slot
  read zero. The block is allocated but empty.

**Status: structurally plausible, NOT verified against game data.** Confirming it needs a loaded
save plus a trainer ID read off the in-game trainer card.

### 🚨 A wrong anchor does not fail — it returns plausible numbers

This is the most expensive failure available here: a reward function trains happily against
noise, and it presents identically to the keypad bug. So the reader's product is a **verifier
that refuses to proceed**, not one that reassures. The strongest check available without knowing
the save is statistical: a Pokémon's personality value is effectively random per creature, so a
correct anchor yields **distinct, high-entropy** values in occupied party slots, while a wrong
one lands in zeros, small counters or printable ASCII — each a separately named check.

Also: **re-read the anchor on every access, never cache it.** The block moves (loading a save, a
heap reshuffle), and a cached pointer keeps returning the old location's bytes — still plausible
numbers, describing a game state that no longer exists.

### ⚠️ Correction accepted: brute-force search cannot establish ownership

A full 16 MB scan for the anchor measures at **~30 seconds** (154k u32 reads/s), which tempted me
to make searching the default rather than trusting a forum constant.

`06-HGSS-MEMORY.md` pushes back and is right: *"Searching for plausible party bytes alone cannot
establish ownership."* A match proves a byte pattern coincides, not that the pointer **owns** the
save block. So the search is a way to *generate candidates cheaply*, not a way to prove one.
It therefore reports **every** hit — two matches mean the probe value is not unique enough to
identify anything, and quietly taking the first is exactly the silent-wrong-anchor failure.
**Resolving `sSaveDataPtr` from the disassembly remains the correct answer**; the search is
scaffolding until that lands.

---

## 4. What still needs a human

- A **loaded save** plus the **trainer ID from the in-game trainer card**, to turn anchor
  plausibility into identification.
- The **`sSaveDataPtr` address for this exact ROM hash**, from matching build symbols — per
  `06-HGSS-MEMORY.md`, absolute anchors are **not** shareable across HG/SS, languages or
  revisions, so each accepted ROM hash needs its own validated resolver.
- A **contention measurement** before any DS broadcast is scheduled, given the 1.06x headroom.

---

## 5. Audit of this work — three real defects in the backend, all fixed

`docs/audits/ds-backend.md` was commissioned specifically to attack the two design decisions
above. It found three, and they are worth recording because two of them defeat the exact
mitigation this document recommends.

1. 🚨 **`verify()` positively identified unrelated memory as a party.** A wrong anchor landing in
   a **table of pointers** (`0x02020000 + 4i`) is distinct, far above `0xFFFF` and not ASCII — so
   it passed every check. **"Distinct and large" is not entropy.** Three checks added, each
   testing the shape a pointer table actually has: reject when every PID is itself a valid
   main-RAM address, when ≥3 PIDs share a top byte, or when they form an arithmetic sequence.
   Verified against the audit's own fixture: now rejected on all three, while realistic PIDs
   still pass.
2. 🚨 **Owning a Python key-mask is NOT sufficient — a save state restores the input registers.**
   Loading one silently re-holds whatever was down when it was captured while `_keys` reads
   empty, and the tick re-writes the pad every frame so the phantom press persists. Exactly the
   failure `release_all()` was written to prevent, reached by a path not considered. Fixed by
   re-asserting the mask after `load_state` and `load_rom`.
3. ⚠️ **Pressing a non-direction button could reverse movement.** Every press re-submits the whole
   mask, and DeSmuME resolves an impossible D-pad with a hidden "most recent direction wins"
   counter — so holding UP then DOWN, then pressing **A**, made UP look newest and flipped the
   character's direction. Fixed by keeping our mask always physically legal (pressing a direction
   clears its opposite), so the sanitiser never has to intervene and re-submission is idempotent.

🔑 All three share the shape this document is about: **none of them raises, and all three would
present as "the model cannot learn."**
