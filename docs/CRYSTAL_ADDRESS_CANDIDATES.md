# Crystal WRAM — CANDIDATE addresses, none verified

🚨 **Do not write any of these into an environment yet.** They are candidates with stated
provenance, not established facts, and the failure mode for getting one wrong is the worst
available in this project: a wrong address does not crash, it returns a plausible number, and a
reward function trains happily against noise. That presents as *"the model cannot learn"* and
sends you to look at the network, the hyperparameters and the reward weights — never at the
address. See [docs/ds/08-MEASURED.md](ds/08-MEASURED.md), where exactly this shaped the HGSS
memory reader.

## Why this file exists

`CRYSTAL_ADDRESSES.md` states plainly that it establishes **no absolute address**: its sandbox
could not read the source (`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`), so it
derived relative layout only. That was the right call and the document should be kept. This file
records what a second attempt produced, at a **lower** standard of evidence, so the two are not
confused with each other.

## Provenance, and why it is weak

These came from a language model **summarising** [pokecrystal's `ram/wram.asm`](https://github.com/pret/pokecrystal/blob/master/ram/wram.asm),
not from parsing it. Two specific reasons to distrust the result:

- It hedged the party struct as *"approximately 48 bytes based on typical Pokémon data
  structures"* — an inference from convention, not a read of `party_struct`.
- It reported section names without quoting the `SECTION` lines that carry the addresses, which
  is the one thing that would let the arithmetic be checked.

| label | candidate | confidence |
|---|---|---|
| `wPartyCount` | `$D2F7` | section start, plausible |
| `wPartySpecies` | `$D2F8` | derived (+1) |
| `wPartyMon1` | `$D2FE` | derived (+7); **stride guessed, not read** |
| `wPlayerID` | `$D2AB` | unchecked |
| `wPlayerName` | `$D2AD` | derived (+2) |
| `wJohtoBadges` | `$D3F5` | unchecked |
| `wKantoBadges` | `$D3F6` | derived (+1) |
| `wEventFlags` | `$D3E0` | unchecked |
| `wMapGroup` / `wMapNumber` | `$D530` / `$D531` | unchecked |
| `wXCoord` / `wYCoord` | `$D532` / `$D533` | derived |

⚠️ `wJohtoBadges` at `$D3F5` sitting *after* `wEventFlags` at `$D3E0` implies the event-flag array
is at most 21 bytes. Crystal has considerably more events than 168 bits. **Either the event
address or the badge address is wrong**, and that contradiction is on the face of the table —
which is the point of writing it down rather than coding from it.

## How to establish them properly, in order of strength

1. **Parse `wram.asm` mechanically.** Walk the `SECTION` directives for their explicit addresses
   and accumulate `ds`/`db`/`dw`/`flag_array` sizes, resolving constants from
   `constants/` (`PARTY_LENGTH`, `NUM_EVENTS`, `NUM_JOHTO_BADGES`, `party_struct`). This is
   arithmetic, not judgement, and it is the answer.
2. **Cross-check against the published symbol file.** pokecrystal builds a `.sym`; a label's
   address there is authoritative and takes two minutes to check.
3. **Confirm against a running game**, exactly as Red's were: Red's addresses were validated by
   reading back a known party member's moves from a real save. Nothing is trusted until a value
   read at an address matches something visible on screen.

## Blocked on

- `repo-crystal/init.state` does not exist. Red's came from the upstream project; Crystal has no
  upstream, so it must be produced by playing through the intro to a defined start point — which
  is also what step 3 above needs.
