**PyBoy is a Game Boy / Game Boy Color emulator and CANNOT run Nintendo DS titles at all. Supporting Gen 4 or Gen 5 requires a different emulator entirely.** This is a new backend and a substantial game-instrumentation project, not an extension of PyBoy’s ROM support. [PyBoy](https://github.com/Baekalfen/PyBoy)

SkyTemple’s **py-desmume** provides Python bindings to DeSmuME, including memory read/write, and ships wheels for Linux, Windows and macOS. **melonDS is the stronger choice for emulation accuracy, but has no comparable official Python binding.** Its accuracy advantage does not establish higher RL throughput or easier integration. [py-desmume](https://github.com/SkyTemple/py-desmume), [memory API](https://py-desmume.readthedocs.io/en/latest/api_docs/desmume.emulator/desmume_memory.html), [melonDS](https://github.com/melonDS-emu/melonDS)

**Recommendation: a full Gen 4/5 extension is not worth committing to yet.** A narrowly scoped feasibility prototype may be worthwhile; multi-title support should wait for measured performance and validated reward instrumentation.

**Evidence limitation:** the requested reads of `README.md`, `docs/DISTRIBUTED.md`, `repo/v2/red_gym_env_v2.py` and `repo/v2/gamespec.py` failed because the execution sandbox could not start: `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. Consequently, this document is provisional, not a completed repository audit. The direct PyBoy dependencies and approximately 38× realtime baseline below come from the task description. Exact methods, configuration fields and distributed-worker behavior remain unverified.

**What must change**

The specific abstraction seam is **between the environment’s action/observation/reset orchestration and the emulator instance**. Every direct use of PyBoy’s `tick`, screen ndarray, memory access and state serialization must cross that boundary.

A proposed `EmulatorBackend` contract would cover:

| Responsibility | Required boundary |
|---|---|
| Lifecycle | Open ROM, initialize settings, close resources |
| Execution | Advance an exact number of emulated frames |
| Input | Set/release buttons; set/release DS touch coordinates |
| Video | Return explicitly ordered screens with documented shape, dtype and buffer ownership |
| Memory | Read/write bytes and typed values in a documented address space |
| State | Capture/restore emulator state, with explicit format/version identity |

These are proposed interface responsibilities, not claims about existing identifiers.

A PyBoy adapter would preserve the current implementation. A DeSmuME adapter would implement the same contract using a different API. py-desmume exposes `cycle(with_joystick=False)`, RGBX framebuffer access, keypad/touch operations and file-based savestates. Its documented state API is not a drop-in replacement for a Python file-like state stream; an adapter must address that difference. [py-desmume implementation](https://raw.githubusercontent.com/SkyTemple/py-desmume/master/desmume/emulator.py)

A second boundary must separate **emulator mechanics from game-state interpretation**. The appropriate role for `gamespec.py`, subject to reading its actual contents, is to identify the supported ROM revision and select game-specific decoders. DS support needs more than replacement address constants: it needs functions that resolve pointers and decode structures into semantic values such as position, party HP, badges, battle state and progression flags.

The remaining changes include:

- **Observations and policy:** define two-screen preprocessing, update observation declarations and CNN dimensions, and retrain. Red policy checkpoints should not be assumed compatible.
- **Actions:** support DS buttons and, where needed, touch. A buttons-only initial task is reasonable only after verifying that its entire required route is reachable.
- **Rewards and termination:** reconstruct progression, exploration, healing, battle and completion signals for each target game. Similar gameplay does not imply identical memory layouts or reward semantics.
- **Resets:** produce DS-specific starting states and restore environment-side reward history and frame stacks alongside emulator state.
- **Distributed execution:** verify process isolation, native-library packaging, worker memory, state transfer and observation transport. Existing scheduling concepts may remain useful, but operational compatibility is unproven.
- **Reproducibility:** record ROM hash, emulator/build version, firmware settings, clock configuration and preprocessing version.

Start with one emulator per worker process. Do not assume that multiple Python objects provide independent native emulator instances.

**Throughput: the decisive unknown**

The supplied Game Boy measurement is **approximately 38× realtime on two ARM cores**. Using approximately 60 emulated frames per second, that corresponds to roughly **2,280 emulated frames per wall-clock second**, under the original benchmark’s accounting.

That is not necessarily 2,280 policy decisions per second. If an action advances \(k\) frames:

\[
\text{decisions/second} \approx \frac{60 \times \text{realtime multiplier}}{k}
\]

Before comparison, establish whether 38× describes one environment or aggregate workers, and whether it includes observation construction, RAM decoding and policy inference.

DS emulation adds two emulated processors, 3D graphics and two displays. These create strong reasons to expect greater cost, but **there is no defensible DS speed estimate for this deployment without measurement**. Neither the pixel ratio nor hardware clock ratios predict emulator throughput.

For illustration only, if a comparable DS benchmark delivered 5× realtime, collecting equal simulated time would take approximately \(38/5 = 7.6\) times longer. At 2× it would take 19 times longer. **These are sensitivity calculations, not performance forecasts.** Equal simulated time also does not imply equal learning progress.

A useful benchmark must:

1. Run on the actual two-core ARM target, with pinned emulator and compiler settings. OS wheel availability does not guarantee Linux ARM support; the inspected PyPI listing did not show an `aarch64` wheel. [Distribution files](https://pypi.org/project/py-desmume/)
2. Exercise representative overworld movement, battles, menus and transitions for the chosen title.
3. Compare core stepping, stepping plus framebuffer extraction, stepping plus RAM decoding, and the complete environment/policy loop.
4. Measure aggregate throughput, per-worker latency, resident memory, reset latency and stability as workers increase.
5. Record rendering configuration, native resolution, frame skipping, audio settings and CPU limits.

Headless execution removes the display window; it does not automatically eliminate rendering needed for visual observations. Frame skipping must preserve correct emulation and produce a fresh observation at the intended decision boundary.

Python overhead also merits measurement: the inspected py-desmume memory-slice implementation loops over native reads rather than performing one bulk read. Large RAM scans every step could therefore be expensive. [Memory-access implementation](https://raw.githubusercontent.com/SkyTemple/py-desmume/master/desmume/emulator.py)

No calendar estimate for competitive DS training is credible until this benchmark exists.

**Observation size and CNN memory**

The native comparison is one **160×144** Game Boy screen against two **256×192** DS screens. py-desmume exposes the combined DS dimensions as 256×384. [DS framebuffer dimensions](https://raw.githubusercontent.com/SkyTemple/py-desmume/master/desmume/emulator.py)

The following values are calculated for uncompressed observations:

| Representation | One Game Boy screen | Both DS screens | Ratio |
|---|---:|---:|---:|
| Pixels | 23,040 | 98,304 | 4.27× |
| Grayscale, uint8 | 22.5 KiB | 96 KiB | 4.27× |
| RGB, uint8 | 67.5 KiB | 288 KiB | 4.27× |
| RGB, float32 | 270 KiB | 1,152 KiB | 4.27× |

For example, **128 observations with four RGB frames each** occupy approximately **33.75 MiB for Game Boy versus 144 MiB for DS** when stored as uint8. Float32 storage raises those figures to **135 MiB versus 576 MiB**, before activations, gradients, optimizer state or extra copies.

These are native-resolution comparisons, not measured increases over this repository’s actual preprocessing. If the current environment downsamples or uses grayscale, its present observation footprint may be substantially smaller.

With unchanged convolution widths and comparable strides, spatially stacking the DS screens would increase much of the convolutional work and activation storage by approximately the pixel ratio. Convolutional parameter counts need not increase; a flattened fully connected layer may grow substantially. Total training memory does not scale uniformly by 4.27×.

Reasonable initial designs are separate screen encoders with feature fusion, or a vertically stacked image. Separate encoders preserve screen identity and avoid convolution across an artificial screen boundary. Channel stacking is also possible but changes first-layer input channels.

Downsampling each DS screen to 128×96 yields **24,576 total pixels**, only **1.07×** the native Game Boy pixel count. That is attractive computationally, but it can destroy small text and menu details. It reduces policy-side cost, not necessarily native emulator rendering cost. A top-screen-only policy similarly needs task-specific justification because useful interaction state appears on the lower screen.

**RAM maps and reverse-engineering maturity**

Gen 4 has substantial public reverse-engineering resources. Calling all of them complete “disassemblies” would be misleading: these projects include C decompilation, assembly and ongoing interpretation work.

| Games | Public project | Verified status and practical implication |
|---|---|---|
| Red/Blue | `pret/pokered` | Mature, buildable disassembly with extensive named RAM definitions; a strong instrumentation reference. |
| Crystal | `pret/pokecrystal` | Mature, buildable disassembly with extensive named RAM definitions, including banked state. |
| Diamond/Pearl | `pret/pokediamond` | README identifies a work-in-progress decompilation and lists builds for US Diamond and Pearl. |
| Platinum | `pret/pokeplatinum` | README identifies a work-in-progress decompilation and lists US revisions 0 and 1. |
| HeartGold/SoulSilver | `pret/pokeheartgold` | Project describes itself as a decompilation; README still calls it a work-in-progress disassembly and lists US builds of both games. |
| Black/White | `squiddonaut/pokeblack`, formerly linked as `pokemodding/pokeblack` | A public Black decompilation exists outside the `pret` organization. Its README identifies Black USA/EUR v1.0; this does not establish White support. |
| Black 2/White 2 | No comparable mature pret project verified in this review | Treat instrumentation coverage as unresolved; do not assume Black layouts transfer to the sequels. |

Sources: [pokered](https://github.com/pret/pokered), [pokecrystal](https://github.com/pret/pokecrystal), [pokediamond](https://github.com/pret/pokediamond), [pokeplatinum](https://github.com/pret/pokeplatinum), [pokeheartgold README](https://raw.githubusercontent.com/pret/pokeheartgold/master/README.md), [pokeblack README](https://raw.githubusercontent.com/squiddonaut/pokeblack/main/README.md).

**No trustworthy, comparable completion percentages were established here.** A matching ROM build does not mean every function is decompiled, every structure named or every runtime field understood. Conversely, incomplete decompilation does not prevent extracting the small subset of state an RL task needs.

The practical difference from the mature Game Boy projects is that extensive named WRAM definitions offer a relatively direct starting point. [Red WRAM](https://raw.githubusercontent.com/pret/pokered/master/ram/wram.asm), [Crystal WRAM](https://raw.githubusercontent.com/pret/pokecrystal/master/ram/wram.asm)

DS instrumentation must account for pointer-based structures and context-dependent state. Platinum’s field-system structures reference other runtime objects; its Pokémon implementation includes encryption/decryption and checksum logic. A source-level field name is therefore not automatically a stable absolute RAM address or a directly readable value. [Platinum field system](https://raw.githubusercontent.com/pret/pokeplatinum/main/include/field/field_system.h), [Pokémon data implementation](https://raw.githubusercontent.com/pret/pokeplatinum/main/src/pokemon.c)

For each exact ROM revision, validate the decoder through movement, battles, menus, map changes and state restoration. Check party values against visible game state and confirm that progression rewards fire once. Silent errors here could invalidate a long training run.

Gen 5 should not be described as having no public reverse engineering. It should be described as having **less established, unverified coverage for this project’s required signals**, especially across White and both sequels.

**Decision and conditions for reconsideration**

**Do not commit to supporting all nine DS titles now.** The combination of an unmeasured ARM backend, larger observations and separate instrumentation work makes the likely maintenance burden substantial, while the expected learning benefit remains unspecified.

If there is a concrete DS-specific research objective, authorize only a bounded prototype for **one Platinum ROM revision**, with py-desmume as the first integration candidate. Platinum has useful public source and structure definitions; this is a practical starting choice, not a claim that it will be fastest.

The decision should change only after the prototype demonstrates:

- Reliable installation and execution on the intended ARM workers.
- End-to-end sample throughput and memory use that fit a stated training budget.
- Repeatable state restoration and stable long-running workers.
- Validated position, party, battle and progression decoders.
- A two-screen policy that learns a small task within an acceptable wall-clock budget.
- A completed audit of the four repository files and a concrete accounting of reusable versus replacement code.

If DeSmuME correctness proves inadequate, melonDS becomes a candidate for additional integration work. Python access through a libretro host exists as an alternative avenue, so “no comparable binding” should not be read as “impossible to control from Python.” That route still needs validation of memory access, state handling and worker isolation. [libretro.py author’s description](https://jesse.tg/blog/libretropy)

Until those conditions are met, **continuing to improve the Game Boy training system is the better-supported investment.**
