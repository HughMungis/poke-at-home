**Proposed chain: 12 milestones, ending with Whitney’s badge and TM.** This uses only event names present in your excerpt; it does not force Crystal into Red’s 17 slots.

Positions are **progress ranks**. Indices are **zero-based bit indices within `wEventFlags`**, counted from `const_def`, including `const_skip`. They are not addresses.

| Position | Event constant | Index | Why it belongs |
|---:|---|---:|---|
| 1 | `EVENT_GOT_A_POKEMON_FROM_ELM` | 26 | Starter received; enables the opening journey. Use this shared flag, not three sequential starter-choice flags. |
| 2 | `EVENT_GOT_MYSTERY_EGG_FROM_MR_POKEMON` | 30 | Reaches the destination of Elm’s opening errand and collects its quest item. |
| 3 | `EVENT_ELM_CALLED_ABOUT_STOLEN_POKEMON` | 67 | Opening quest turns into the return-to-lab sequence. |
| 4 | `EVENT_GAVE_MYSTERY_EGG_TO_ELM` | 31 | Completes the errand and opens onward progression through Route 30. |
| 5 | `EVENT_DUDE_TALKED_TO_YOU` | 65 | Records the Route 29 tutorial offer after the errand. Watching the tutorial is unnecessary. |
| 6 | `EVENT_GOT_TM31_MUD_SLAP` | 8 | **Proxy:** Falkner defeated, first badge awarded, and his TM collected. |
| 7 | `EVENT_GOT_TOGEPI_EGG_FROM_ELMS_AIDE` | 45 | Required for the normal Route 32 passage south in Crystal. |
| 8 | `EVENT_CLEARED_SLOWPOKE_WELL` | 43 | Resolves the Azalea Rocket blockade and enables gym progression. |
| 9 | `EVENT_GOT_TM49_FURY_CUTTER` | 9 | **Proxy:** Bugsy defeated, second badge awarded, and his TM collected. |
| 10 | `EVENT_HERDED_FARFETCHD` | 41 | Completes the Ilex Forest task that enables receiving Cut. |
| 11 | `EVENT_GOT_HM01_CUT` | 16 | Provides Cut; with Bugsy’s badge, enables passage toward Goldenrod. |
| 12 | `EVENT_GOT_TM45_ATTRACT` | 11 | **Proxy:** Whitney defeated, crying dialogue resolved, third badge awarded, and TM collected. |

The opening handoff unlocks Route 30, and the tutorial-offer flag is set even if the demonstration is declined. [Elm’s lab script](https://github.com/pret/pokecrystal/blob/master/maps/ElmsLab.asm), [Route 29 script](https://github.com/pret/pokecrystal/blob/master/maps/Route29.asm). Crystal’s Route 32 gate explicitly checks the Togepi Egg receipt. [Route 32 script](https://github.com/pret/pokecrystal/blob/master/maps/Route32.asm).

**This is a proposed normal-route reward order, not a strict dependency graph.** Collect gym TMs immediately to preserve that order: TM receipt can be delayed by a full bag. Their flags indicate more than victory alone. [Falkner script](https://github.com/pret/pokecrystal/blob/master/maps/VioletGym.asm), [Bugsy script](https://github.com/pret/pokecrystal/blob/master/maps/AzaleaGym.asm), [Whitney script](https://github.com/pret/pokecrystal/blob/master/maps/GoldenrodGym.asm).

For exact gym victories, the scripts confirm `EVENT_BEAT_FALKNER`, `EVENT_BEAT_BUGSY`, and `EVENT_BEAT_WHITNEY`; their indices are **UNVERIFIED from the supplied excerpt**. Do not substitute `EVENT_MADE_WHITNEY_CRY` (index 40) as a permanent milestone: it is subsequently cleared, and victory initially precedes badge receipt. [Whitney script](https://github.com/pret/pokecrystal/blob/master/maps/GoldenrodGym.asm).

**Red milestone correspondence and missing analogues**

| Red stage(s) | Crystal correspondence or absence |
|---|---|
| 1 — Followed Oak into lab | **NO direct analogue.** Crystal has Elm’s introduction, but no Oak escort sequence or corresponding flag in this excerpt. |
| 2 — Got starter | Direct counterpart: Crystal position 1. |
| 3 — Rival battle in Oak’s lab | **NO lab-battle analogue.** Crystal’s first rival encounter occurs in Cherrygrove on the return journey; it falls between positions 3 and 4. Its completion flag/index is **UNVERIFIED from this excerpt**. |
| 4 — Oak’s Parcel | **NO literal parcel analogue.** The Mystery Egg collection and delivery serve the opening-errand role: positions 2 and 4. |
| 5 — Got Pokédex | Exists: Oak gives it at Mr. Pokémon’s house, after the Mystery Egg. It uses an engine flag rather than a supplied `EVENT_*` constant; an event-array index is **not applicable**. [House script](https://github.com/pret/pokecrystal/blob/master/maps/MrPokemonsHouse.asm) |
| 6 — Poké Balls from Oak | **NO Oak-gift analogue.** Elm’s aide supplies the functional equivalent after delivery; the script uses scene state, not a dedicated receipt event here. [Lab script](https://github.com/pret/pokecrystal/blob/master/maps/ElmsLab.asm) |
| 7 — Town Map | Functional counterpart: the optional Pokégear Map Card from Cherrygrove’s guide. It is not a required milestone or a supplied event-array flag. [Cherrygrove script](https://github.com/pret/pokecrystal/blob/master/maps/CherrygroveCity.asm) |
| 8 — Optional Route 22 rival | **NO separate equivalent optional opening rival battle.** Do not count Cherrygrove twice to fill both Red rival slots. |
| 9, 11, 17 — Brock, Misty, Lt. Surge | Gym-order counterparts: Falkner, Bugsy, Whitney; positions 6, 9, 12. |
| 10 — Cerulean rival | Functional counterpart: Azalea rival before onward travel through Ilex Forest. A completion flag/index is **UNVERIFIED from the excerpt**; do not assume an NPC visibility event means victory. |
| 12 — Met Bill | **NO early critical-path analogue.** Crystal’s Bill encounter belongs to Ecruteak, beyond this endpoint. |
| 13 — Cell separator | **NO analogue.** Crystal has no Bill transformation/rescue sequence. |
| 14 — S.S. Ticket | **NO early-Johto analogue.** `EVENT_GOT_SS_TICKET_FROM_ELM` exists at index 36, but belongs after the Elite Four, not before gym three. [Lab script](https://github.com/pret/pokecrystal/blob/master/maps/ElmsLab.asm) |
| 15 — HM01 | Direct counterpart: position 11; obtained through the Farfetch’d task instead of a ship captain. |
| 16 — S.S. Anne left | **NO analogue in this progression.** Crystal’s later S.S. Aqua events do not gate early Cut or Whitney. |

Do not pad the chain with initialization, temporary map flags, optional Flash, tutorial completion, or Togepi hatching. For monotonic rewards, retain the highest achieved progress rank externally.
