**Gen 3 requires a GBA emulator backend. mGBA’s upstream Python bindings are the strongest first candidate.** Ruby, Sapphire, Emerald, FireRed and LeafGreen are Game Boy Advance games: PyBoy supports GB/GBC, and DeSmuME is a DS emulator. Neither is the appropriate backend for these titles. [PyBoy](https://github.com/Baekalfen/PyBoy), [mGBA](https://github.com/mgba-emu/mgba)

**Gen 3 is a materially easier integration target than Gen 4/5**, principally because it has one screen, no touchscreen and extensive pret source coverage across all five games. It still requires a new emulator adapter and substantial game-state decoding. In particular, Pokémon-record encryption already exists in Gen 3.

This study uses upstream source/documentation and the supplied `gamespec.py`. No emulator installation, ROM execution or throughput benchmark was performed. Runtime compatibility, ARM deployment and training performance are **UNVERIFIED**.

**Python-scriptable GBA emulator options**

| Candidate | Memory access | Save-state support | Assessment |
|---|---|---|---|
| **mGBA upstream Python bindings** | Typed signed/unsigned 8-, 16- and 32-bit reads/writes; bus and raw access; named GBA memory regions | `save_raw_state()` and `load_raw_state()` expose native state capture/restoration | Best initial candidate for a focused backend adapter |
| **libretro.py with the mGBA core** | Core-exported memory pointers/views and memory-map descriptors; coverage depends on the core | `serialize_size()`, `serialize()` and `unserialize()` | Credible alternative; requires frontend callbacks and explicit address mapping |
| **Stable-Retro with its GBA support** | RAM observations and memory-defined game variables | Starting-state files and environment restoration; implementation uses emulator state capture/restoration | Useful Python/Gymnasium route, but brings its own integration framework |

The mGBA binding exists **inside the upstream repository**, rather than being merely a proposed community wrapper. It exposes ROM loading, `reset()`, `run_frame()`, button masks and a configurable video buffer. Its raw state saver returns a CFFI buffer, so the adapter must define copying, ownership and serialization into transportable bytes; this is not PyBoy’s file-like state API. Cartridge-save loading is a separate operation. [Core implementation](https://raw.githubusercontent.com/mgba-emu/mgba/master/src/platform/python/mgba/core.py)

Its GBA wrapper exposes EWRAM, IWRAM and other memory regions. Typed memory views provide reads and writes, but slices perform individual native reads in a Python loop. Do not assume a large memory slice is an efficient bulk transfer. [GBA wrapper](https://raw.githubusercontent.com/mgba-emu/mgba/master/src/platform/python/mgba/gba.py), [memory implementation](https://raw.githubusercontent.com/mgba-emu/mgba/master/src/platform/python/mgba/memory.py)

libretro.py supplies execution, callback registration, memory access and serialization APIs; mGBA’s libretro core supports save states. However, an exported RAM region is not automatically a complete CPU address-space accessor. The adapter must establish how addresses in pret symbols map to exported regions, including IWRAM pointers and EWRAM data. Complete coverage and reliable restoration through this combination are **UNVERIFIED** here. [libretro.py API](https://libretropy.readthedocs.io/en/latest/api/libretro.core/), [mGBA core documentation](https://docs.libretro.com/library/mgba/)

Stable-Retro documents GBA support, RAM observations, variable definitions and state-based resets. Its environment implementation also exposes the underlying state workflow. It is worth considering if adopting its integration conventions would reduce work; ready-made, validated integrations for these five Pokémon games and arbitrary memory-write coverage are **UNVERIFIED** in this review. [Supported systems](https://github.com/Farama-Foundation/stable-retro), [Python API](https://stable-retro.farama.org/python/), [environment implementation](https://stable-retro.farama.org/_modules/stable_retro/retro_env/)

These alternatives are different Python integration routes and may use the **same mGBA emulation core**. A comparably suitable direct Python binding for another GBA core is **UNVERIFIED** here; absence from this shortlist does not establish that none exists.

**Compared with PyBoy’s maturity**

PyBoy offers a documented Python-oriented workflow for frame stepping, button control, screen arrays, memory and state handling, with explicit machine-learning use cases. It is also the backend already assumed by this project. mGBA has the necessary upstream API surface, but that alone does not establish equivalent Python packaging, documentation, API stability or operational experience. [PyBoy documentation and examples](https://github.com/Baekalfen/PyBoy)

The practical conclusion is **promising capability, unproven deployment parity**. For mGBA’s Python bindings, the following remain **UNVERIFIED**:

- Installation on the intended two-core ARM workers, including compatible native-library and Python builds.
- Long-running stability, reset fidelity and independence between emulator instances.
- State portability across builds and complete handling of cartridge saves and RTC state.
- End-to-end throughput relative to the supplied PyBoy baseline.

Start with one emulator per worker process and pin the native core and Python binding together.

**pret coverage**

Gen 3 has established pret projects covering **all five requested games**. These are primarily C decompilation resources, whereas `pokered` and `pokecrystal` are assembly disassemblies.

| Games | Project | Verified coverage and practical value |
|---|---|---|
| Red/Blue | [`pret/pokered`](https://github.com/pret/pokered) | Buildable disassembly and extensive named RAM definitions |
| Crystal | [`pret/pokecrystal`](https://github.com/pret/pokecrystal) | Buildable disassembly, including named banked state |
| Emerald | [`pret/pokeemerald`](https://github.com/pret/pokeemerald) | Emerald decompilation with Pokémon structures, event handling, map data and save-block code |
| FireRed/LeafGreen | [`pret/pokefirered`](https://github.com/pret/pokefirered) | English builds for both titles; README lists original and revision-1 images |
| Ruby/Sapphire | [`pret/pokeruby`](https://github.com/pret/pokeruby) | Source project covering both titles and listing matching ROM hashes; repository description calls it a decompilation, while its README retains “disassembly” wording |

For instrumentation, Gen 3 is much closer to the established Gen 1/2 reference situation than to the uneven Gen 5 coverage described in the supplied study. Named C structures and accessor implementations explain both where information lives and how the game interprets it.

**Exact completion percentages are UNVERIFIED.** A matching build does not prove that every field is understood. Build symbols must match the selected ROM hash, language and revision; addresses must not be transferred blindly between titles or revisions.

**Observation space**

GBA supplies one **240×160** screen, compared with GB/GBC’s **160×144**. An image array normally expresses these as `(160, 240, channels)` and `(144, 160, channels)` respectively. mGBA defines the GBA dimensions explicitly. [GBA interface](https://raw.githubusercontent.com/mgba-emu/mgba/master/include/mgba/gba/interface.h)

Calculated native-resolution storage:

| Representation | GB/GBC | GBA | Ratio |
|---|---:|---:|---:|
| Pixels | 23,040 | 38,400 | 1.67× |
| Grayscale, uint8 | 22.5 KiB | 37.5 KiB | 1.67× |
| RGB, uint8 | 67.5 KiB | 112.5 KiB | 1.67× |
| RGB, float32 | 270 KiB | 450 KiB | 1.67× |

For **128 observations containing four RGB frames**, uint8 storage rises from **33.75 MiB to 56.25 MiB**. Float32 storage rises from **135 MiB to 225 MiB**, before model activations and other allocations.

This is considerably smaller than the supplied DS comparison of 98,304 pixels across two screens. There is no screen-fusion decision or artificial boundary between displays.

Update observation declarations, preprocessing and any shape-dependent policy layers. Convolutional weights need not grow with image dimensions, but activations and flattened fully connected inputs may grow. Total training memory does not necessarily increase by exactly 1.67×. Downsampling to 120×80 is a possible prototype choice, subject to checking text and menu readability. Existing policy compatibility is **UNVERIFIED**.

**Party structures: already encrypted, but partially easy to read**

The answer is mixed: **the Pokémon core resembles Gen 4’s encrypted-block approach more than Gen 2’s plain records; party HP and level remain straightforward.**

Emerald’s source defines an 80-byte boxed record and a 100-byte party record. The party extension contains unencrypted status, level, HP, maximum HP and battle stats. Species and moves reside inside the boxed record’s protected substructures; both use 16-bit fields. [Pokémon structures](https://raw.githubusercontent.com/pret/pokeemerald/master/include/pokemon.h)

The protected area contains four 12-byte blocks. Each 32-bit word is XORed with the personality value and original-trainer ID; block placement follows one of 24 orders selected by personality modulo 24. A checksum validates the decrypted contents. These are Gen 3 rules, not a license to reuse a Gen 4 decoder. [Encryption, block selection and accessors](https://raw.githubusercontent.com/pret/pokeemerald/master/src/pokemon.c)

The supplied `GameSpec` consequently needs behavioral overrides:

- `read_hp()` currently reads big-endian values; GBA HP requires little-endian decoding.
- `party_species()` currently assumes one directly readable byte per species.
- `knows_move()` currently scans four adjacent bytes; Gen 3 requires decrypted, correctly ordered 16-bit move IDs.
- Party stride and level/HP offsets change.
- Opponent and active-battle state need separate validation; party storage is not automatically the authoritative representation for every battle signal.

Decode a copied record without modifying emulated memory, validate its checksum, and compare results against the game’s party and summary screens. Addresses and cross-title decoder behavior remain **UNVERIFIED** until tested against each supported ROM.

**Event flags: closer to Gen 2, with pointer handling**

Gen 3 event flags are ordinary packed bits, **not encrypted Pokémon blocks**. Emerald resolves ordinary flags through `gSaveBlock1Ptr->flags`, selecting byte `flag_id / 8` and bit `flag_id & 7`. Script variables are separate 16-bit values, and special flags use another region. [Event implementation](https://raw.githubusercontent.com/pret/pokeemerald/master/src/event_data.c)

The complication is locating the live save block. Emerald explicitly relocates its save blocks and updates pointers. A fixed absolute `event_flags_start` is therefore insufficient: read the current pointer and add the verified structure offset. Ruby/Sapphire’s event implementation instead accesses `gSaveBlock1` directly, demonstrating why a single addressing rule should not be assumed across Gen 3. [Emerald relocation](https://raw.githubusercontent.com/pret/pokeemerald/master/src/load_save.c), [Ruby/Sapphire events](https://raw.githubusercontent.com/pret/pokeruby/master/src/event_data.c)

For the supplied spec design:

- Replace fixed-range event assumptions with semantic flag access and dynamically resolved storage where needed.
- Derive badges from named badge flags.
- Use selected permanent milestones and relevant script variables for progression.
- Exclude temporary, daily and reversible state from one-time progress rewards.
- Validate flag ordering when constructing observations; the current `event_bits()` emits MSB-first strings, while flag IDs address bits LSB-first.

The existing callable-based memory seam remains useful. Gen 3 needs more overrides than the two structural differences currently implemented in `Gen2Spec`.

**Actions and relative difficulty**

**There is no touchscreen.** Assuming the existing seven actions are **Up, Down, Left, Right, A, B and Start**, that action vocabulary is a reasonable starting point. GBA also has Select, L and R, all represented by mGBA’s input API. [GBA button definitions](https://raw.githubusercontent.com/mgba-emu/mgba/master/src/platform/python/mgba/gba.py)

A complete route using only those seven actions is **UNVERIFIED**. Check required menus, field moves, bicycle sequences and input timing. Button combinations or altered hold durations may help particular tasks, even where additional physical buttons are unnecessary.

Nevertheless, Gen 3 is **materially easier as an engineering target** than Gen 4/5: one modestly larger screen, familiar button navigation and source coverage across every requested title remove substantial integration uncertainty. This is not evidence that its campaigns will require fewer RL samples, or that seven-action control is impossible on DS.

**Prototype, throughput and ordering**

Keep the emulator boundary separate from game interpretation. The backend should provide ROM lifecycle, exact frame advancement, button state, framebuffer extraction, memory access and state capture/restoration. A Gen 3 spec should turn that memory into validated position, party, battle and progression signals.

The supplied approximately **38× realtime** PyBoy baseline does not support a numerical GBA forecast. **GBA throughput is UNVERIFIED**; neither the 1.67× pixel ratio nor console clock rates predict it.

Before scaling training:

1. Install a pinned mGBA/Python build on the actual ARM target.
2. Benchmark stepping alone, then video extraction, RAM decoding and the complete environment loop across movement, battles, menus and transitions.
3. Measure reset latency, memory use, aggregate worker throughput and long-running stability.
4. Restore states repeatedly and compare subsequent observations and decoded state under identical actions, controlling RTC and cartridge-save behavior.
5. Validate rewards and termination on a short route, then demonstrate learning within a stated wall-clock budget.

Reset environment-side reward history, exploration state and frame stacks alongside emulator state. The supplied `TiledWorld` can provide a starting design, but derive map capacity and coordinate bounds from the chosen game instead of inheriting Crystal’s guessed dimensions.

**Recommendation: extend to Gen 3 before Gen 4/5.** Start with one exact Emerald ROM revision and mGBA’s upstream Python bindings; Emerald provides a well-supported reference for the encrypted party and pointer-based save structures that the new spec must handle. If the binding proves operationally troublesome, evaluate the mGBA libretro route or Stable-Retro before abandoning GBA.

Expand to the remaining Gen 3 titles after the backend and first decoder pass validation. This ordering establishes the reusable emulator abstraction with a single-screen, button-controlled system, while introducing richer memory decoding under substantially better source coverage than the DS expansion offers.
