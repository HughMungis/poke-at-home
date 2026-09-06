# Crystal WRAM derivation audit

## Evidence and limits

Local file reads failed before execution with:

```text
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

This document therefore uses only the supplied excerpts. Neither `gamespec.py` nor `constants_map_constants.asm` was readable. **No absolute address is established by the available evidence.**

The visible section declarations, `"Enemy Party"` at line 2821 and `"Party"` at line 3409, specify `WRAMX` without an address or bank. A section walk establishes offsets within a section; establishing its absolute base additionally requires placement evidence. Source order alone does not establish that separate sections are contiguous. Address-looking labels such as `wd430` are not placement declarations.

All WRAM line references below refer to `ram_wram.asm`. Arithmetic uses decimal numbers unless prefixed with `0x`.

## Derivable relative layout

### Party

Let `P` be the unresolved absolute base of section `"Party"` (line 3409). `PARTY_LENGTH = 6` is defined in `constants_pokemon_data_constants.asm:135`.

| Symbol | WRAM line | Running arithmetic | Absolute address |
|---|---:|---|---|
| `wPartyCount` | 3413 | First allocation: `P + 0x00` | Unresolved |
| `wPartySpecies` | 3414 | Count occupies one byte: `P + 0x01` | Unresolved |
| `wPartyEnd` | 3415 | Six species bytes: `P + 1 + 6 = P + 0x07` | Unresolved |
| `wPartyMon1` | 3419–3420 | One terminator byte: `P + 1 + 6 + 1 = P + 0x08`; first loop expansion | Unresolved |

The species list and party structs are separate allocations.

### Party struct offsets and size

The field layout is declared in `constants_pokemon_data_constants.asm:75–113`; WRAM line 3420 invokes `party_struct`. Its macro implementation is not supplied.

Let `M = NUM_MOVES`. Its definition is absent from the supplied excerpts. The offsets below follow the declared `rsreset`/`rsset` layout.

| Field or boundary | Constants line(s) | Running arithmetic from struct start |
|---|---:|---|
| Species | 77 | `0` |
| Held item | 78 | `0 + 1 = 1` |
| **Moves** | 79 | `1 + 1 = 2 = 0x02`; occupies `M` bytes |
| OT ID | 80 | `2 + M` |
| Experience | 81 | `2 + M + 2 = 4 + M` |
| Stat experience | 82–88 | `4 + M + 3 = 7 + M`; explicit five words advance by `10` |
| DVs | 89 | `7 + M + 10 = 17 + M` |
| PP | 90 | `17 + M + 2 = 19 + M`; occupies `M` bytes |
| Happiness | 91 | `19 + 2M` |
| Pokérus | 92 | `20 + 2M` |
| Caught data | 93–99 | `21 + 2M`; occupies two bytes; `rsset` aliases do not add storage |
| **Level** | 100 | `23 + 2M` |
| Box struct end / status | 101–102 | `24 + 2M` |
| Padding | 103 | `25 + 2M` |
| **Current HP** | 104 | `26 + 2M`; two bytes |
| **Max HP** | 105 | `28 + 2M`; two bytes |
| Battle stats | 106–112 | `30 + 2M`; explicit five words advance by `10` |
| **Party struct size** | 113 | `40 + 2M` |

The explicit fields after `rsset MON_STAT_EXP` and `rsset MON_STATS` establish their final extents without needing the values of `NUM_EXP_STATS` or `NUM_BATTLE_STATS`.

**Conditional calculation only:** if a readable definition establishes `NUM_MOVES = 4`, the results become moves `0x02`, level `0x1F`, current HP `0x22`, max HP `0x24`, and size `0x30`. Those numeric substitutions remain unverified here.

### Map identity and coordinates

Let `C` be the unresolved address of `wCurMapData` (line 3380), and let `S = ceil(NUM_SPAWNS / 8)`.

| Allocation | WRAM lines | Running position afterward |
|---|---:|---|
| Visited-spawn flags | 3382 | `C + S` |
| Dig warp/group/number | 3384–3386 | `C + S + 3` |
| Backup warp/group/number | 3390–3392 | `C + S + 6` |
| Padding | 3394 | `C + S + 9` |
| Last-spawn group/number | 3396–3397 | `C + S + 11` |
| Warp number | 3399 | `C + S + 12` |

| Symbol | WRAM line | Relative address | Absolute address |
|---|---:|---|---|
| `wMapGroup` | 3400 | `C + S + 0x0C` | Unresolved |
| `wMapNumber` | 3401 | `C + S + 0x0D` | Unresolved |
| `wYCoord` | 3402 | `C + S + 0x0E` | Unresolved |
| `wXCoord` | 3403 | `C + S + 0x0F` | Unresolved |

Thus group, number, Y, and X are four consecutive bytes. Their adjacency is established independently of the missing base.

### Badges

Let `J` be the unresolved address of `wJohtoBadges`.

| Symbol | WRAM line | Arithmetic | Absolute address |
|---|---:|---|---|
| `wJohtoBadges` | 3106 | `J`; reserves `ceil(NUM_JOHTO_BADGES / 8)` bytes | Unresolved |
| `wKantoBadges` | 3107 | `J + ceil(NUM_JOHTO_BADGES / 8)`; reserves `ceil(NUM_KANTO_BADGES / 8)` bytes | Unresolved |

Neither badge-count constant is defined in the supplied excerpts.

### Event flags

Let `E` be the unresolved address of `wEventFlags` at line 3263, and `N = NUM_EVENTS`.

```text
byte length          = ceil(N / 8) = floor((N + 7) / 8)
start                = E
end, exclusive       = E + floor((N + 7) / 8)
last byte, inclusive = E + floor((N + 7) / 8) - 1   [for N > 0]
```

`wCurBox` at line 3265 immediately follows the allocation, so its address equals the exclusive end. There is no explicit event-flags end label in this excerpt.

A checkable local walk begins at `T = address(wPokecenter2FSceneID)`:

| Allocation | WRAM lines | Running position afterward |
|---|---:|---|
| Scene IDs: `3227 − 3149 + 1 = 79` bytes | 3149–3227 | `T + 79` |
| Padding: 49 bytes | 3229 | `T + 128` |
| Fight counts: `3259 − 3232 + 1 = 28` bytes | 3232–3259 | `T + 156` |
| Padding: 100 bytes | 3261 | `T + 256 = T + 0x100` |

Therefore `E = T + 0x100`. Neither `T` nor the final value of `NUM_EVENTS` is established by the supplied excerpts.

## UNRESOLVED

| Requested result | Missing evidence |
|---|---|
| Absolute `wPartyCount`, `wPartySpecies`, `wPartyMon1` | Placement and bank of section `"Party"` (line 3409). |
| Numeric party size, level offset, current-HP offset, max-HP offset | Definition of `NUM_MOVES`. The actual `party_struct` macro is also needed to verify that its allocation matches the constants. Moves offset `0x02` is established by the constants. |
| Absolute `wMapGroup`, `wMapNumber`, `wXCoord`, `wYCoord` | Placement of `"Enemy Party"` (line 2821), a complete size walk to line 3380, and the referenced constants/macros, including `NUM_SPAWNS`. |
| Absolute `wJohtoBadges`, `wKantoBadges` | Same section placement and preceding size dependencies, plus the badge-count definitions. |
| Absolute event-flags start and end | Same section placement and preceding size dependencies, plus the full event enumeration through `NUM_EVENTS`. Only event-file lines 1–40 were supplied. |
| `wIsInBattle` address and WRAM line | Its declaration is absent from the supplied excerpt. `wBattleMode` at lines 2720–2724 has documented battle-state values, but no evidence establishes it as an alias or replacement for `wIsInBattle`. |
| `wEnemyMonLevel` address and exact field declaration | Line 2713 invokes `battle_struct wEnemyMon`; the macro defining its level offset and the preceding section placement/walk are unavailable. Party offsets cannot establish a battle-struct offset. |
| CUT move ID | Move enumeration or an explicit `CUT` definition. `EVENT_GOT_HM01_CUT` at event-file line 23 is an event flag, not a move ID. |
| Exact differences from the existing Red spec | `gamespec.py` could not be read. `constants_map_constants.asm` also could not be read, preventing verification of map-group and map-number definitions. |

The walk through `"Enemy Party"` also encounters unions and macros. The 451-byte union comment at line 2823 is useful as a check, but a complete derivation must calculate each branch and use its maximum extent. Adding branch lengths would be incorrect.

## Structural requirements for Gen2Spec

The supplied Crystal declarations establish these implementation requirements; comparison with the actual Red implementation remains unresolved:

- Represent map identity using both group and number. Coordinates follow in **Y, X** order.
- Read separate Johto and Kanto badge arrays using their defined lengths.
- Use Crystal’s party layout, including held item, happiness, Pokérus, caught data, and separate Special Attack/Special Defense fields. The constants explicitly declare a Red struct length of `44` at line 116; do not substitute it for Crystal’s derived stride.
- Keep the species list, party structs, OT names, and nicknames distinct (WRAM lines 3413–3433).
- Derive the battle-mon level independently of the party-mon level.
- Size event storage from `NUM_EVENTS`. The first eight event flags are explicitly temporary until map reload (event-file lines 4–12), so counting all flags does not measure only persistent progress.
- Verify word byte order from the relevant read/write code before implementing HP decoding; allocation declarations establish width, not serialization order.
