# HGSS memory research for `Gen4Spec`

**UNVERIFIED — runtime integration:** No absolute RAM address or pointer anchor in this document has been validated against Frank’s ROM or a real HGSS save state. The relative layouts below are sufficient to build a decoder and resolver, but not to register a working `HeartGoldSpec` or `SoulSilverSpec`.

**VERIFIED** means supported by the named pret source structure, accessor, or script. It does **not** mean tested in DeSmuME. Derived structure offsets are identified explicitly. **UNVERIFIED** marks missing runtime evidence, incomplete semantic checks, and proposed implementation choices.

## 1. Resolve live objects before reading quantities

**VERIFIED — `SaveData_Get`, `SaveArray_Get`:** Save-backed quantities reside in a live `SaveData` allocation. `SaveArray_Get` uses an offset table inside that allocation; a save-file offset is not an absolute RAM address. The global pointer is `sSaveDataPtr`. [src/save.c](https://github.com/pret/pokeheartgold/blob/master/src/save.c)

**VERIFIED — `SaveData`, `SaveArrayHeader`, derived offsets:** Given a validated `SaveData *S`, reproduce the accessor as:

```python
# All reads are from emulated memory, little-endian.
header = S + 0x23014 + 0x10 * save_array_id
block = S + 0x10 + u32(header + 0x08)
```

`dynamic_region` is embedded at `S+0x10`; it is not a pointer. `arrayHeaders` starts at `S+0x23014`, and each header’s `offset` is at `+8`. [include/save.h](https://github.com/pret/pokeheartgold/blob/master/include/save.h)

**VERIFIED — save-array IDs:** Player data is `1`, party `2`, flags/variables `4`, and local field data `5`. [constants/save_arrays.h](https://github.com/pret/pokeheartgold/blob/master/include/constants/save_arrays.h)

**VERIFIED — field root:** `sFieldSysPtr` refers to the allocated `FieldSystem`. Its initialization and destruction are managed by the field application. [src/field_system.c](https://github.com/pret/pokeheartgold/blob/master/src/field_system.c)

**VERIFIED — `FieldSystem`, derived offsets:**

| Relative location | Value |
|---|---|
| `F+0x00` | `FieldProcessManager *` |
| `F+0x0C` | `SaveData *` |
| `F+0x20` | `Location *` |
| `F+0x40` | `PlayerAvatar *` |

These are pointer fields, requiring dereferencing. [include/field_system.h](https://github.com/pret/pokeheartgold/blob/master/include/field_system.h)

**UNVERIFIED — missing anchors:** The addresses of `sSaveDataPtr` and `sFieldSysPtr` for the target ROM remain unresolved. Obtain them from a matching build’s symbols or identify their loads in the matching executable. Validate their lifecycle across boot, Continue, reset, and state restoration. Searching for plausible party bytes alone cannot establish ownership.

## 2. Party count, species, level, HP, and moves

### Container and record layout

**VERIFIED — `SaveArray_Party_Get`, `Party_GetCount`, `Party_GetMonByIndex`:** The normal player party is save array `SAVE_PARTY`. Read occupied slots using its count. [src/party.c](https://github.com/pret/pokeheartgold/blob/master/src/party.c)

**VERIFIED — `PartyCore`, `Pokemon`, `BoxPokemon`, `PartyPokemon`; offsets from declarations:**

| Location | Width | Meaning |
|---|---:|---|
| `P+0` | 32 bits | Maximum count |
| `P+4` | 32 bits | Current count |
| `P+8+236*i` | 236 bytes | Pokémon slot `i` |
| Record `+0x00` | 32 bits | Personality |
| `+0x04` | 16 bits | State bits: party decrypted, box decrypted, checksum failed, at bits 0–2 |
| `+0x06` | 16 bits | Box checksum |
| `+0x08..+0x87` | 128 bytes | Four shuffled 32-byte blocks |
| `+0x88..+0xEB` | 100 bytes | Party extension |
| Logical block A `+0` | 16 bits | Species |
| Logical block B `+0,+2,+4,+6` | 16 bits each | Moves |
| Decoded record `+0x8C` | 8 bits | Level |
| Decoded record `+0x8E` | 16 bits | Current HP |
| Decoded record `+0x90` | 16 bits | Maximum HP |

All multibyte values use little-endian interpretation. These HP/level offsets refer to **decoded** data. [include/pokemon_types_def.h](https://github.com/pret/pokeheartgold/blob/master/include/pokemon_types_def.h)

### Exact decoding procedure

**VERIFIED — `_MonEncryptSegment`, `_MonDecryptSegment`, `MonEncryptionLCRNG`:** For each successive little-endian 16-bit word, advance the 32-bit seed first, then XOR with its upper half. Encryption and decryption are identical:

```python
def crypt(segment, seed):
    out = bytearray(segment)
    for j in range(0, len(out), 2):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        word = int.from_bytes(out[j:j+2], "little") ^ (seed >> 16)
        out[j:j+2] = word.to_bytes(2, "little")
    return out
```

The stream continues across the entire segment; do not restart at block boundaries. [src/math_util.c](https://github.com/pret/pokeheartgold/blob/master/src/math_util.c)

**VERIFIED — `ENCRY_ARGS_BOX`, `ENCRY_ARGS_PTY`, `GetSubstruct`, `CalcMonChecksum`, lock functions:** Decode `[8:136]` with the checksum seed unless `boxDecrypted` is set. Independently decode `[136:236]` with the personality seed unless `partyDecrypted` is set. The checksum is the sum of the 64 decoded boxed words, modulo `65536`; the extension is excluded.

Select the block permutation with:

```python
selector = ((personality >> 13) & 31) % 24
```

The following strings describe **physical block order**, indexed by `selector`:

```text
ABCD ABDC ACBD ACDB ADBC ADCB
BACD BADC BCAD BCDA BDAC BDCA
CABD CADB CBAD CBDA CDAB CDBA
DABC DACB DBAC DBCA DCAB DCBA
```

For example, `ACDB` places logical B in physical slot 3. Decrypt before extracting blocks. A checksum match cannot validate the permutation because summation is order-independent.

The game temporarily decrypts records in place. Lock release recomputes the checksum before re-encrypting; a locked record undergoing modification can therefore have a stale checksum. [src/pokemon.c](https://github.com/pret/pokeheartgold/blob/master/src/pokemon.c)

**UNVERIFIED — implementation acceptance policy:** Read a coherent, paused snapshot into a private buffer. Reject checksum-failed records and inconsistent snapshots; retry at a stable execution boundary. Do not “repair” game RAM, assume every record is encrypted, or reinterpret a checksum failure as an empty party.

### Required real-save validation

**UNVERIFIED — tests still required before trusting observations:**

- Match party count, slot order, species, all moves, level, and both HP values to the actual game.
- Include species and moves above `255`, and HP above `255`, to expose width/endian errors.
- Test different personalities, especially permutations that distinguish a permutation from its inverse. Cover all 32 selectors synthetically.
- Compare multiple captures, party reordering, deposits/withdrawals, eggs, fainting, healing, and level-ups.
- Verify both encrypted and temporarily decrypted record handling.
- Confirm checksums and values after cold boot, Continue, and save-state restoration.
- Confirm the decoded objects belong to the player’s current party rather than a menu, opponent, old allocation, or battle copy.

## 3. Decoded battle copies: useful, but not an overworld replacement

**VERIFIED — `BattleContext.battleMons`, `BattleMon`:** A decoded active-battler representation exists. It contains species, moves, level, current HP, and maximum HP as ordinary fields. There are four battler slots, not six player-party slots. `BattleMon.hp` is signed 32-bit and `maxHp` is unsigned 32-bit. Access through:

```text
BattleSystem.ctx
    -> BattleContext.battleMons[battler]
    -> species / level / hp / maxHp
```

Use target-compiled `offsetof`/`sizeof` values for these structures; this document does not supply an experimentally verified numeric `battleMons` offset or stride. [include/battle/battle.h](https://github.com/pret/pokeheartgold/blob/master/include/battle/battle.h)

**VERIFIED — `BattleSetup_SetParty`, `sub_0205239C`, `BattleSetup_Delete`:** Battle setup allocates separate `Party` objects, copies the player party into them, and later copies results back. Those objects still use the ordinary `Pokemon` representation; the term “battle party” does not imply plaintext. They are freed during cleanup. [src/battle/battle_setup.c](https://github.com/pret/pokeheartgold/blob/master/src/battle/battle_setup.c)

**VERIFIED — `Battle_Run`:** Battle execution has initialization, main, cleanup, and evolution phases; its battle heap is destroyed during completion. This establishes that battle working storage is not an enduring overworld data source. [src/battle/battle_022378C0.c](https://github.com/pret/pokeheartgold/blob/master/src/battle/battle_022378C0.c)

**UNVERIFIED — synchronization detail:** The exact frame-by-frame synchronization between active `BattleMon` HP, battle-party HP, and save-party HP has not been established here. Do not assume the save party reflects each attack immediately.

**UNVERIFIED — proposed observation policy:** Decode the save party outside battle. During battle, resolve the battle party and reconcile active battlers through their selected party indices. Validate this before computing total-party HP fractions. Reading only active battlers would omit benched members.

## 4. In-battle state and opponent level

### Battle detection

**VERIFIED — `Battle_LaunchApp`, `gOverlayTemplate_Battle`:** The field launches a specific child application with `Battle_Init`, `Battle_Main`, `Battle_Exit`, and overlay `OVY_12`. Identify that application rather than treating any child application as battle. [src/launch_application.c](https://github.com/pret/pokeheartgold/blob/master/src/launch_application.c)

**VERIFIED — `OverlayManager`, derived offsets:** Once the child manager `M` has been resolved, its copied template starts at `M+0`; execution callback is `M+4`, overlay ID `M+0xC`, procedure state `M+0x14`, arguments pointer `M+0x18`, and data pointer `M+0x1C`. [include/overlay_manager.h](https://github.com/pret/pokeheartgold/blob/master/include/overlay_manager.h)

**VERIFIED — application lifecycle:** `FieldSystem_LaunchApplication` also disables field execution for nonbattle applications. Consequently, `!runningFieldMap`, a non-null child, or inability to move is insufficient to identify battle. [src/field_system.c](https://github.com/pret/pokeheartgold/blob/master/src/field_system.c)

**UNVERIFIED — concrete detector:** Resolve `F → processManager → child`, compare its template with the matching ROM’s battle template, then interpret the battle procedure state. The absolute callback addresses, final state predicate, and transition behavior remain untested. Battle application lifetime includes phases where active battler data is unavailable, including postbattle evolution.

**VERIFIED — result is not activity:** `Encounter_GetResult` writes the completed result to `VAR_BATTLE_RESULT`. That variable is not a live in-battle Boolean. [src/encounter.c](https://github.com/pret/pokeheartgold/blob/master/src/encounter.c)

### Opponent level

**VERIFIED — accessors:** `BattleSystem_GetBattleContext` exposes the context. `BattleSystem_GetFieldSide` determines side using battler metadata. `BattleSystem_GetParty` handles party selection differently for doubles, multi, and tag battles. [src/battle/battle_system.c](https://github.com/pret/pokeheartgold/blob/master/src/battle/battle_system.c)

**UNVERIFIED — proposed contract:** Return the maximum level among valid, active opposing battlers. Return a documented no-opponent value outside active battle; do not read stale battler slots. If compatibility requires “maximum of the entire opposing party,” decode that party instead—these are different measurements.

**UNVERIFIED — remaining resolver gap:** The ownership chain from the battle application’s data to the live `BattleSystem` allocation, plus numeric battler offsets, requires completion and runtime validation. Never cast the application’s data pointer to `BattleSystem *` merely because the resulting numbers look reasonable.

## 5. Sixteen badges, stored in nonadjacent bytes

**VERIFIED — `PlayerProfile`, derived layout:** The two fields are:

| Relative to profile `R` | Field |
|---|---|
| `R+0x1A` | `u8 johtoBadges` |
| `R+0x1F` | `u8 kantoBadges` |

Other profile fields occupy the intervening bytes. [include/player_data.h](https://github.com/pret/pokeheartgold/blob/master/include/player_data.h)

**VERIFIED — profile resolution:** `Save_PlayerData_GetProfile` returns the profile embedded in save array `1`. With the declared two-byte `Options` followed by aligned `PlayerProfile`, the derived profile offset is `+4`; badge offsets relative to the player-data block are therefore `+0x1E` and `+0x23`. Verify compiler layout when exporting offsets. [src/player_data.c](https://github.com/pret/pokeheartgold/blob/master/src/player_data.c), [include/options.h](https://github.com/pret/pokeheartgold/blob/master/include/options.h)

**VERIFIED — `PlayerProfile_TestBadgeFlag`:** Badge indices `0..7` use Johto bit `index`; indices `8..15` use Kanto bit `index-8`. Count both bytes’ set bits. [src/player_data.c](https://github.com/pret/pokeheartgold/blob/master/src/player_data.c)

**VERIFIED — badge ordering:**

| Bits | Order, least-significant first |
|---|---|
| Johto `0..7` | Zephyr, Hive, Plain, Fog, Storm, Mineral, Glacier, Rising |
| Kanto `0..7` | Boulder, Cascade, Thunder, Rainbow, Soul, Marsh, Volcano, Earth |

[constants/badge.h](https://github.com/pret/pokeheartgold/blob/master/include/constants/badge.h)

**UNVERIFIED — proposed API:** Supply 16 observation bits in badge-index order and override extraction. `badge_bytes=2` must not cause an inherited adjacent-byte read. Validate a Kanto-only change as well as a Johto badge award.

## 6. Map identity and coordinates

**VERIFIED — `Location`:** This is five 32-bit integers: map ID at `+0`, warp ID at `+4`, X at `+8`, Y at `+0xC`, direction at `+0x10`. Use the full map ID, not one byte or a Gen 2 group/number pair. [include/field_types_def.h](https://github.com/pret/pokeheartgold/blob/master/include/field_types_def.h)

**VERIFIED — saved location:** Save array `5` begins with `LocalFieldData.currentPosition`; `LocalFieldData_GetCurrentPosition` returns it. This identifies stored location data, not proof that its coordinates update on every walking frame. [src/save_local_field_data.c](https://github.com/pret/pokeheartgold/blob/master/src/save_local_field_data.c)

**VERIFIED — live avatar:** `PlayerAvatar.mapObject` is at derived offset `+0x30`. The avatar’s X/Z accessors read that object. [include/player_avatar.h](https://github.com/pret/pokeheartgold/blob/master/include/player_avatar.h), [src/player_avatar.c](https://github.com/pret/pokeheartgold/blob/master/src/player_avatar.c)

**VERIFIED — `LocalMapObject`:** Current X is unsigned 32-bit at `+0x64`; current Z is unsigned 32-bit at `+0x6C`. The intervening signed Y field is elevation. [include/map_object.h](https://github.com/pret/pokeheartgold/blob/master/include/map_object.h)

**VERIFIED — coordinate semantics:** Field code obtains standing tile coordinates from avatar X/Z; warp code maps Z into `Location.y`. Thus `GameSpec.coords` should expose the planar pair `(X,Z)` as `(x,y)`. [src/field/field_control.c](https://github.com/pret/pokeheartgold/blob/master/src/field/field_control.c), [src/field_warp_tasks.c](https://github.com/pret/pokeheartgold/blob/master/src/field_warp_tasks.c)

**UNVERIFIED — proposed live read, pending coherent-transition testing:**

```python
location = u32(F + 0x20)
avatar = u32(F + 0x40)
obj = u32(avatar + 0x30)
return u32(obj + 0x64), u32(obj + 0x6C), s32(location)
```

Do not dereference an avatar during teardown. Test walking, door warps, connected outdoor maps, stairs, surfing, and battle return.

**VERIFIED — map namespace:** `MAP_ID_MAX` is `540`; identifiers extend through `539`, including special/unused entries. Map headers separately identify matrices, map sections, and scripts. These identifiers are not interchangeable. [constants/maps.h](https://github.com/pret/pokeheartgold/blob/master/include/constants/maps.h), [src/data/map_headers.h](https://github.com/pret/pokeheartgold/blob/master/src/data/map_headers.h)

**UNVERIFIED — world sizing:** Reserve at least the map-ID namespace if using direct map slots. Maximum coordinate extents and special-map instance identity remain unvalidated. Do not reuse a `72×72` modulo projection without measuring bounds; it can silently merge distinct positions.

## 7. Event flags and critical-path progress

### Storage and addressing

**VERIFIED — `SaveVarsFlags`:** Save array `4` contains variables first, followed by packed flags. [include/save_vars_flags.h](https://github.com/pret/pokeheartgold/blob/master/include/save_vars_flags.h)

**VERIFIED — constants:** There are `0x170` 16-bit variables, beginning at variable ID `0x4000`. Thus flags begin at block offset `0x2E0`. [constants/vars.h](https://github.com/pret/pokeheartgold/blob/master/include/constants/vars.h)

**VERIFIED — flag ranges:** `NUM_FLAGS=2912`: `364` bytes, IDs `0..0xB5F`. Separate temporary flags occupy IDs `0x4000..0x403F`. Map-temporary flags begin at `1`, count `64`; daily flags begin at `0xAA0`, count `192`. [constants/flags.h](https://github.com/pret/pokeheartgold/blob/master/include/constants/flags.h)

**VERIFIED — `Save_VarsFlags_GetFlagAddr`:** For save-backed flag `f`, read:

```python
flags_start = save_array_4 + 0x2E0
flags_end = flags_start + 0x16C       # exclusive
bit = (read_m(flags_start + f // 8) >> (f % 8)) & 1
```

Flag zero is a no-op in the accessor. Temporary flags use separate `sTempFlags` storage. IDs between the allocated save range and temporary range are not valid merely because they are below `0x4000`. Variables use their own accessor and namespace. [src/save_vars_flags.c](https://github.com/pret/pokeheartgold/blob/master/src/save_vars_flags.c)

**UNVERIFIED — proposed observation policy:** Expose 2,912 raw bits, indexed by flag ID, with bit zero normalized to false. Keep raw observation extraction separate from reward eligibility. Exclude temporary, daily, initialization, and reversible state from monotonic progress rewards.

### Named progress candidates

**VERIFIED — identifiers and numeric definitions only:** The following names exist in `constants/flags.h`. **UNVERIFIED — milestone suitability:** Except where separately noted, their setters, reset behavior, and exact completion semantics have not been audited here.

| Flag ID | Source symbol |
|---|---|
| `0x06A` | `FLAG_GOT_STARTER` |
| `0x06B` | `FLAG_GOT_POKEDEX` |
| `0x079` | `FLAG_GAVE_RIVAL_NAME_TO_OFFICER` |
| `0x07B` | `FLAG_BEAT_AZALEA_ROCKETS` |
| `0x07D`, `0x07E` | `FLAG_FOUND_FIRST_FARFETCHD`, `FLAG_FOUND_SECOND_FARFETCHD` |
| `0x080` | `FLAG_GOT_HM01` |
| `0x0B9` | `FLAG_GOT_SECRETPOTION` |
| `0x0C9` | `FLAG_GOT_RED_SCALE` |
| `0x0CA` | `FLAG_ROCKET_HIDEOUT_CLEARED` |
| `0x0C6` | `FLAG_BEAT_RADIO_TOWER_ROCKETS` |
| `0x0E4..0x0E7` | `FLAG_DEFEATED_WILL`, `KOGA`, `BRUNO`, `KAREN` |
| `0x0F2` | `FLAG_GOT_SS_TICKET_FROM_ELM` |
| `0x118` | `FLAG_RESTORED_POWER` |
| `0x185` | `FLAG_GOT_HM08` |
| `0x964` | `FLAG_GAME_CLEAR` |

[constants/flags.h](https://github.com/pret/pokeheartgold/blob/master/include/constants/flags.h)

**VERIFIED — game-clear semantics:** `CallTask_GameClear` sets both the script game-clear flag and profile game-clear bit. It also accepts a `vsTrainerRed` argument; the already-set game-clear bit alone cannot distinguish a later Red victory. [src/game_clear.c](https://github.com/pret/pokeheartgold/blob/master/src/game_clear.c)

**VERIFIED — meaningful accessors:** `CheckGotStarter`, `CheckGotPokedex`, and `CheckRocketHideoutCleared` read the corresponding named flags. Conversely, step-taken, costume, and Strength-active flags have explicit clear/change operations and represent reversible state. [src/sys_flags.c](https://github.com/pret/pokeheartgold/blob/master/src/sys_flags.c)

**UNVERIFIED — replacement for `required_events`:** A complete HGSS equivalent of the 17-milestone Red chain is not established. Build it from typed predicates—flags, badges, learned moves, and verified variable thresholds—rather than forcing every milestone into a single flag.

**UNVERIFIED — critical gaps to close:**

| Progress segment | Required verification |
|---|---|
| Elm’s initial errand | Completion predicate beyond naming the rival |
| Gym progression | Badge award timing; distinguish winning from receiving the badge |
| Ilex Forest | HM receipt versus actually knowing Cut |
| Sudowoodo | Route-cleared predicate covering noncapture outcomes |
| Ecruteak | Burned Tower and Surf-access predicates |
| Olivine | Medicine obtained versus delivered |
| Blackthorn | Dragon’s Den completion and Rising Badge award |
| Version legendary sequence | Encounter completed versus captured; HG/SS alternatives |
| League | Whether individual Elite Four flags reset between attempts |
| Kanto | Power restoration, radio upgrade, Snorlax passage, remaining badges |
| Final completion | Mount Silver access and a persistent Red-victory predicate |

For each predicate, inspect the relevant map header’s script bank, every setter/clearer, and before/after real states. Do not substitute a capture flag for clearing an obstacle without checking all outcomes.

## 8. HeartGold versus SoulSilver

**VERIFIED — source targets:** pret identifies these US ROM builds:

| Game | SHA-1 |
|---|---|
| HeartGold | `4fcded0e2713dc03929845de631d0932ea2b5a37` |
| SoulSilver | `f8dc38ea20c17541a43b58c5e6d18c1732c7e582` |

[Repository README](https://github.com/pret/pokeheartgold)

**VERIFIED — shared declarations:** The cited party, profile, flag-storage, and field structures are shared declarations without HG-versus-SS alternatives in those definitions. This supports a shared structural decoder. It does not establish identical linked addresses.

**UNVERIFIED — binary compatibility:** Sharing absolute anchors across HG/SS, languages, revisions, or patched ROMs is unsupported. Each accepted ROM hash needs its own validated resolver configuration.

**UNVERIFIED — content handling:** The Ho-Oh/Lugia progression branch, version-specific encounters, and any affected essential-map ordering require separate script audits. A single unconditional legendary milestone must not be assumed correct for both games.

## 9. Implementation boundary and release criteria

**VERIFIED — supplied `gamespec.py`:** Its inherited methods assume byte-sized species/moves/counts, fixed addresses, big-endian HP, and contiguous flag/badge access. HGSS therefore needs method overrides, not merely new constants.

**UNVERIFIED — proposed implementation requirements:**

- Resolve pointers afresh after reset and state restoration.
- Decode occupied party members once per coherent observation.
- Override count, species, levels, moves, HP fraction, badges, coordinates, flags, battle state, and opponent level.
- Distinguish unavailable memory from legitimate zeros; unresolved anchors must fail explicitly.
- Define battle-phase semantics and party-copy synchronization before rewarding HP changes.
- Preserve flag-ID ordering explicitly; inherited MSB-first byte formatting reverses bits within each byte.
- Keep `required_events` and map-progress rankings disabled until their predicates are validated.

**UNVERIFIED — release blockers:** Runtime root addresses, battle-system ownership, real-save decoder agreement, battle HP synchronization, coordinate behavior across transitions, and the complete progress chain remain outstanding. Source-verified offsets should not be promoted to a usable concrete spec until those checks pass.
