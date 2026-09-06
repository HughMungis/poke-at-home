# UNRESOLVED

The local files could not be read. Every read attempt failed before command execution with:

```text
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

Consequently, no section bases, source line numbers, addresses, or offsets were verified. Providing numerical values would violate the requirement to derive them from these files.

| Requested symbol or value | Missing evidence |
|---|---|
| `wPartyCount`, `wPartySpecies`, `wPartyMon1` | Relevant section base and all preceding allocation sizes in `ram_wram.asm`. |
| Party struct size; moves, level, current HP, max HP offsets | Struct constants and layout, including any macro definitions used to allocate the struct. |
| `wMapGroup`, `wMapNumber`, `wXCoord`, `wYCoord` | Relevant section bases and preceding allocations. |
| `wJohtoBadges`, `wKantoBadges` | Relevant section base and preceding allocations. |
| `wEventFlags` start and end | Section walk to its start and the verified value of `NUM_EVENTS` from `constants_event_flags.asm`. |
| `wIsInBattle`, `wEnemyMonLevel` | Relevant section bases, preceding allocations, and any applicable struct expansion. |
| Move ID for `CUT` | A readable move constant definition or equivalent authoritative local mapping. Its presence in the directory could not be checked. |
| Crystal differences that `Gen2Spec` must handle | Readable Crystal layouts and constants, plus `gamespec.py` for comparison with the existing Red spec. |

For the event array, the required arithmetic once its inputs are verified is:

```text
byte_count    = floor((NUM_EVENTS + 7) / 8)
exclusive_end = start + byte_count
inclusive_end = start + byte_count - 1
```

Completion requires restored local file-reading access or the file contents supplied directly. No addresses have been inferred from memory or substituted from an upstream revision.
