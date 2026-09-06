**Recommend building the matching pokecrystal revision to obtain linker symbols, then validating those symbols against controlled emulator save states.** The build establishes placement; runtime tests establish that the addresses and decoding describe the game actually being played.

No absolute addresses are established by this plan itself.

| Option | Cost | Trustworthiness | Verification against a real save state |
|---|---|---|---|
| **Build pokecrystal → `.sym` and `.map`** | Moderate setup: obtain the source, install its required RGBDS version and build dependencies, and select the correct ROM target. Repeat builds are inexpensive. | Strongest provenance: addresses come from the linker. Applicability still depends on matching the running ROM and interpreting banks and fields correctly. | Load a state from the target ROM, read the symbol locations, and compare with independently recorded party, map, badge, and battle observations. Repeat after controlled gameplay changes. |
| **Published RAM map** | Lowest initial effort: collect candidate addresses and documented meanings. Missing banks, version information, or fields can increase verification work. | Useful secondary evidence, potentially incomplete or for a different release. Agreement with another list is not runtime verification. | Treat every entry as a hypothesis. Apply the same state tests as for symbols, including changes that distinguish live data from cached copies. |
| **Empirical emulator search** | Little build setup, but substantial manual work per field. Party count and HP are approachable; event identities, allocation boundaries, and bank distinctions are harder. | Strong evidence for observed behavior after repeated experiments; weak evidence from a single matching value. It does not automatically recover source symbol names or full layouts. | Discover candidates using some states, then test predictions on separate states that were not used to select the candidates. Use access watchpoints when several candidates survive. |

The official [build instructions](https://github.com/pret/pokecrystal/blob/master/INSTALL.md) describe the toolchain and release targets. The [Makefile](https://github.com/pret/pokecrystal/blob/master/Makefile) explicitly invokes the linker with `layout.link` and emits both `.sym` and `.map` files. A published candidate source is the [Data Crystal RAM map](https://datacrystal.tcrf.net/wiki/Pok%C3%A9mon_Crystal/RAM_map).

1. **Identify the exact target and preserve evidence.** Record the running ROM’s hash, language/revision, emulator version, and original save state. Work on copies. Record expected values from the game’s UI or independently observed gameplay before inspecting candidate addresses.

   Restore the state through its emulator and inspect decoded WRAM. Do not treat a CPU address as a byte offset into the serialized state file. If the input is a battery save, load it in-game first and capture an emulator state.

2. **Obtain reproducible placement evidence.** Pin a pokecrystal commit and install the toolchain specified by that commit. Build the matching release target: normally `make` for `pokecrystal.gbc`, or `make crystal11` for the corresponding revision. Retain the matching `.sym`, `.map`, build log, source commit, and tool versions.

   Compare the built ROM byte-for-byte with the ROM used by the emulator. A mismatch means the build is not yet established as the correct reference.

   Extract each requested symbol as **bank plus CPU address**, together with its width and decoding. Resolve constants and macros from the same checkout: party stride, move count, badge lengths, event count, and battle-struct offsets. Inspect field access code for byte order and semantics. Do not substitute `wBattleMode` for `wIsInBattle` without establishing the intended behavior.

3. **Construct controlled before-and-after states.** Use ordinary gameplay to produce changes wherever practical. For empirical discovery, search all relevant WRAM banks, retain all matching candidates, and intersect candidates across successive observations. Avoid creating the expected result by writing to the address being tested.

   | Data | Concrete experiment and required prediction |
   |---|---|
   | Party count, species, and stride | Start with several distinguishable Pokémon. Record their order, levels, moves, and HP. Swap two slots, then deposit one Pokémon. Count and species order must follow the changes; complete party records must move at the predicted stride. |
   | Level, moves, and HP | Damage and heal one Pokémon; teach a move or level up. The corresponding fields must decode to the displayed values. Use unequal HP bytes to distinguish byte orders; include HP above 255 when feasible to exercise the high byte. |
   | Map identity and coordinates | Capture settled states before and after one horizontal step, one vertical step, and a map transition. X and Y must change independently as predicted. Check absolute coordinates against a known tile position and map IDs against the matching map definitions; movement alone proves neither absolute origin nor identity. |
   | Johto and Kanto badges | Capture states before and after earning a known badge in each region. The expected bit must change in the appropriate array and agree with the trainer card. |
   | Event flags | Choose a named event whose setting code is identified. Capture before and after completing it, then reload the map or game as appropriate. Verify the predicted byte and bit, allowing for other events changed by the same action. Check allocation length independently from `NUM_EVENTS` and the following symbol; one event cannot prove the whole boundary. |
   | Battle state and enemy level | Capture overworld, wild-battle, trainer-battle, and post-battle states. Check the state field’s actual encoding and compare enemy level with the battle display across different opponents. Evaluate enemy data only when valid for the current battle phase. |

4. **Separate discovery from validation.** Freeze the candidate table, then load a second independently prepared save state with a different party and location. Run the same reader through the application’s actual memory API, checking its bank selection against the emulator debugger. A candidate must keep working after menus close, maps change, and the state is restored.

   For unresolved duplicate candidates, use read/write watchpoints to identify which location gameplay routines actually consume. Published-map agreement can corroborate this evidence but cannot replace it.

5. **Publish a checkable result.** For each field, record symbol or descriptive name, bank, address, size, decoding, provenance, tested state hashes, expected values, observed values, and verification status. Leave untested fields explicitly unresolved.

**What would falsify the result:** a reproducible mismatch between a field’s prediction and controlled gameplay in a matching ROM, after checking bank selection and observation timing. Examples include a party record failing to follow a slot swap, decoded HP disagreeing with the display, X changing on vertical movement, or the predicted event bit failing to track its event.

A ROM mismatch falsifies the claim that the build is a matching reference. Multiple surviving memory candidates leave identification unresolved. Neither case justifies marking the addresses verified.
