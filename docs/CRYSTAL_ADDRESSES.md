# Crystal WRAM Derivation

## UNRESOLVED

I could not read the supplied files. Both filesystem tool attempts failed before executing with:

```text
failed to spawn code-mode host /usr/local/bin/codex-code-mode-host:
No such file or directory (os error 2)
```

No addresses, line numbers, sizes, offsets, or move IDs were verified. Providing them from memory would violate the required derivation method.

| Requested symbol or value | Missing evidence |
|---|---|
| `wPartyCount`, `wPartySpecies`, `wPartyMon1` | Relevant section base and all preceding allocation sizes in `ram_wram.asm`. |
| Party struct size; moves, level, current HP, max HP offsets | Party struct layout and any macro definitions it invokes, plus size constants in `constants_pokemon_data_constants.asm`. |
| `wMapGroup`, `wMapNumber`, `wXCoord`, `wYCoord` | Relevant section bases and allocation walks in `ram_wram.asm`. |
| `wJohtoBadges`, `wKantoBadges` | Relevant section base and preceding allocations in `ram_wram.asm`. |
| `wEventFlags` start and end | Allocation walk to its start and the derived value of `NUM_EVENTS` from `constants_event_flags.asm`. |
| `wIsInBattle`, `wEnemyMonLevel` | Relevant section bases, preceding allocations, and any struct macro definitions. |
| Move ID for `CUT` | The move constant enumeration defining `CUT`; I could not determine whether the supplied files contain it. |
| Structural differences from Red that `Gen2Spec` must handle | Verified Crystal layouts and the existing Red implementation in `gamespec.py`. |

For an event array starting at address `S`, the arithmetic to check once the files are accessible is:

```text
reserved bytes = ceil(NUM_EVENTS / 8) = (NUM_EVENTS + 7) // 8
exclusive end  = S + reserved bytes
last byte      = S + reserved bytes - 1
```

The requested document remains incomplete because file access failed; no numerical derivations were possible.
