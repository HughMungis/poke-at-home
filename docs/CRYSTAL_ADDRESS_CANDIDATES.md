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
not from parsing it. It hedged the party struct as *"approximately 48 bytes based on typical
Pokémon data structures"* — an inference from convention rather than a read of `party_struct`.

🚨 **Then I downloaded the file and checked, and the provenance is worse than "weak" — the
addresses are not in it at all.** Measured against the real `ram/wram.asm` (3,760 lines):

```
sections total : 71
with an address:  0
```

Every section is declared `WRAM0` or `WRAMX` with **no address and no bank** —
`SECTION "Party", WRAMX` is the literal line. Absolute addresses are assigned by the **linker**,
not written in the source, so **no absolute WRAM address is derivable from `wram.asm` by any
amount of careful arithmetic.** The numbers above were recalled from training data and presented
as if read from the file.

Two further tells, now confirmed:

- **`wPartyMon1` does not exist as a label** anywhere in `wram.asm`. It was invented.
- Real source order is `wJohtoBadges` (line 3106) → `wEventFlags` (3263) → `wXCoord` (3403) →
  `wPartyCount` (3413), i.e. **badges come before event flags**. The table has that backwards,
  which is exactly the self-contradiction flagged below — now explained.

✅ This **completely vindicates `CRYSTAL_ADDRESSES.md`**, which reached the same conclusion from
excerpts alone: *"A section walk establishes offsets within a section; establishing its absolute
base additionally requires placement evidence."* That was right, and this table is the
counter-example proving it.

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
which is the point of writing it down rather than coding from it. (Confirmed above: real source
order puts badges *before* event flags, so the table has the relationship inverted.)

## How to establish them properly, in order of strength

1. ~~**Parse `wram.asm` mechanically.**~~ **This does not work and I was wrong to suggest it.**
   The sections are floating — no address, no bank — so there is no base to add offsets to. A
   section walk yields relative layout only, which is precisely what `CRYSTAL_ADDRESSES.md`
   already produced.
2. **Build pokecrystal and read the symbol file. This is the answer.** `rgbds` emits a `.sym`
   mapping every label to the address the linker actually chose, which is authoritative by
   construction because it is the same arithmetic the ROM was built with. Verify the built ROM's
   hash matches `f2f52230b536214ef7c9924f483392993e226cfb` first — a symbol file is only valid
   for the binary it was produced alongside.
3. **Confirm against a running game**, exactly as Red's were: Red's addresses were validated by
   reading back a known party member's moves from a real save. Nothing is trusted until a value
   read at an address matches something visible on screen.

## Blocked on

- `repo-crystal/init.state` does not exist. Red's came from the upstream project; Crystal has no
  upstream, so it must be produced by playing through the intro to a defined start point — which
  is also what step 3 above needs.
