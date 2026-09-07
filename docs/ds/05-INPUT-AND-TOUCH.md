**Recommend a state-gated touch interface, with named, frame-timed gestures and a general touch interface retained for validation. Do not certify any title’s full route as buttons-only from the evidence collected here.**

**VERIFIED** below means supported by an identified manual or inspected source handler—not a completed emulator playthrough. **UNVERIFIED** means the game behavior remains unproven; linked player reports are leads, not verification. I could inspect web sources, but local execution failed with the sandbox’s `bwrap` error, so no ROM replay was performed.

**1. Main-story reachability**

Define the benchmark as **New Game through first credits**, without glitches, external saves or human intervention. Test any longer completion objective separately. Starting after an introductory touch interaction changes the benchmark; it does not establish buttons-only completion from New Game.

| Titles | Buttons-only verdict | Mandatory touch and unresolved points |
|---|---|---|
| Diamond/Pearl | **UNVERIFIED: likely no from New Game.** | **UNVERIFIED:** Rowan’s introductory Poké Ball reportedly requires touch. I did not obtain the corresponding input handler or verify button alternatives. The claim that everything afterward is buttons-only also remains **UNVERIFIED**. [Player report](https://www.reddit.com/r/miniSNESmods/comments/10iozh9) |
| Platinum | **VERIFIED: no from New Game**, from the inspected intro state machine. | **VERIFIED:** Rowan’s Poké Ball requires a new touch within a radius of 16 pixels around **(128,100)**. Physical buttons instead trigger instructions to use touch. **VERIFIED:** entering the optional Control Info branch creates another touch-only Yes/No interaction; that branch can be avoided. **UNVERIFIED:** absence of additional mandatory touch after the intro. [Intro source: `RowanIntro_WasPokeballOpened`, `RI_STATE_PKBL_WAIT_INPUT`, `RI_STATE_CONTROL_INFO_WAIT_INPUT`](https://raw.githubusercontent.com/pret/pokeplatinum/main/src/applications/rowan_intro/rowan_intro_app.c) |
| HeartGold/SoulSilver | **UNVERIFIED: buttons-only completion is plausible, but not established end to end.** | **VERIFIED:** starter selection does **not** require touch: `getInput` implements navigation and successive A-button confirmation through completion. **VERIFIED:** official documentation supports button alternatives for menus and name entry. **UNVERIFIED:** absence of a touch-only gate across the complete route, including introductory help branches and later progression. [Starter handler](https://raw.githubusercontent.com/pret/pokeheartgold/master/src/choose_starter_app.c), [Nintendo manual](https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/DS_Pokemon_HeartGold) |
| Black/White | **UNVERIFIED: do not authorize buttons-only training.** | **UNVERIFIED:** the Nimbasa Musical dress-up tutorial is reported as a compulsory progression gate requiring touch. Whether tapping completion with no props suffices, or a drag is necessary, is unresolved. **UNVERIFIED:** introductory Poké Ball touch requirements and absence of later gates. Reports conflict with blanket buttons-only advice. [Tutorial report](https://gamefaqs.gamespot.com/boards/989552-pokemon-black-version/58586686), [additional report](https://www.forums.desmume.org/viewtopic.php?pid=25220), [conflicting advice](https://gamefaqs.gamespot.com/boards/989552-pokemon-black-version/58127839) |
| Black 2/White 2 | **UNVERIFIED: buttons-only completion is plausible, not certified.** | No mandatory touch point was verified. **UNVERIFIED:** complete button coverage of the opening, Pokéstar Studios tutorial and publication sequence, Join Avenue introduction, PWT introduction, and remaining story. These are audit checkpoints, not assertions that they require touch. [Buttons-only discussion—not proof](https://gamefaqs.gamespot.com/boards/661226-pokemon-black-version-2/65169485) |

This is **not a verified exhaustive inventory**. In particular, I have not established that every unlisted interaction is touch-optional, or that findings transfer across paired versions, languages and revisions.

There is also a separate button-space defect: **VERIFIED:** Diamond and HeartGold’s manuals assign opening the menu to **X**. Retaining only the supplied seven actions fails to expose that documented control. Add X explicitly; do not silently reinterpret START. [Diamond manual](https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/DS_Pokemon_Diamond), [HeartGold manual](https://csassets.nintendo.com/noaext/image/private/t_KA_PDF/DS_Pokemon_HeartGold)

**2. Action-space choices**

For comparison, let \(B=8\): the existing seven actions plus X. This is a proposed baseline, **not a verified sufficient button set for every title**. The backend should expose all physical buttons; promote additional buttons or combinations into the policy after route validation.

Assume fixed-duration tap macros unless stated otherwise.

| Design | Action count | Exploration and coverage |
|---|---:|---|
| Discretised touch grid | \(B+WH\). An 8×6 grid gives **56**; 16×12 gives **200**. With the original seven: 55 and 199. | Broad spatial coverage, but cell centres can miss small targets. Tap-only actions cannot express dragging. |
| Grid with persistent contact | \(B+WH+1\): **57** or **201**, including release. | Selecting a cell presses or moves the held stylus; release lifts it. Supports drag sequences, but adds temporal credit assignment and persistent input state. |
| Named hotspots | \(B+H\). Four hotspots give **12**. Add \(D\) named drag gestures: \(12+D\). | Much less spatial exploration. Every omitted target or required gesture is a possible hard block. Four is an illustrative budget, not an audited requirement. |
| State-gated named gestures | Fixed policy space \(B+H+D\), with **8 valid actions normally**, and \(8+h_s+d_s\) in relevant states. | Avoids spending ordinary exploration on touch. A false-negative state detector can make progress impossible. Requires actual policy masking, including during training. |

Counts assume buttons and touch are mutually exclusive at each decision. Simultaneous button-and-touch control requires additional combinations or a factored policy.

Using your **570,000 decisions per evaluation**, uniform random sampling would select a particular action approximately:

| Available actions | Selections per action |
|---:|---:|
| 7 | 81,429 |
| 8 | 71,250 |
| 12 | 47,500 |
| 56 | 10,179 |
| 200 | 2,850 |

These are **calculations, not learning-time predictions**. Under the same simplified model, an exact \(L\)-action sequence becomes \((N/7)^L\) less probable when expanding from 7 to \(N\) actions. Actual PPO behavior depends on state visitation, masking and learned preferences.

A larger action space does not itself multiply emulator stepping time. Measure decisions/second separately from learning efficiency; longer gestures also change emulated frames per decision.

**3. What py-desmume exposes**

**VERIFIED—binding source and API documentation:**

- `emu.input.touch_set_pos(x, y)` sets the touched position; there is no separate `touch_press()` method.
- `emu.input.touch_release()` lifts contact.
- Neither method accepts duration. Hold time comes from advancing emulation between setting contact and releasing it.
- `emu.cycle(with_joystick=False)` advances one frame. The inspected signature actually defaults to **`True`**, so pass `False` explicitly.
- The wrapper defines screen dimensions as **256×192** and combined height as **384**. [Input API](https://py-desmume.readthedocs.io/en/latest/api_docs/desmume.emulator/desmume_input.html), [binding source](https://raw.githubusercontent.com/SkyTemple/py-desmume/master/desmume/emulator.py)

Define adapter coordinates as native bottom-screen pixels, **x=0…255, y=0…191**, origin at top left. Validate that mapping against the pinned native core and firmware calibration; the Python method’s brief documentation alone does not establish clipping or calibration behavior. Never pass coordinates from the resized CNN observation or add the composed display’s vertical offset.

A proposed tap, entered with all inputs released:

```python
def tap(emu, x, y, hold_frames, total_frames):
    assert 0 <= x < 256 and 0 <= y < 192
    assert 1 <= hold_frames < total_frames

    emu.input.touch_set_pos(x, y)
    for _ in range(hold_frames):
        emu.cycle(with_joystick=False)

    emu.input.touch_release()
    for _ in range(total_frames - hold_frames):
        emu.cycle(with_joystick=False)
```

Deterministic replay requires:

- **Exact scheduling:** input transitions before specified frames, with a sampled release interval between taps. No wall-clock sleeps.
- **Explicit gesture semantics:** for dragging, record each coordinate update and its frame while contact remains held.
- **Controlled initial state:** pin ROM hash, core/binding build, firmware/calibration, clock behavior, save data and emulator settings.
- **Exclusive input ownership:** disable joystick, GUI mouse and other uncontrolled input producers.
- **Complete restoration:** restore adapter-held buttons, contact, pending gesture phase, masks and observation history alongside emulator state. Prefer checkpoints at neutral action boundaries.
- **Replay evidence:** replay identical traces from identical states, including resets and mid-contact restoration tests; compare observations and relevant state across repeated runs and workers.

The API’s existence does **not** verify those guarantees.

**4. Recommended implementation and falsification**

Implement **state-gated named gestures**, initially for the proposed Platinum prototype, with both screens observable and a general coordinate/contact API underneath.

Use a fixed `Discrete(8 + H + D)` policy space and versioned action mapping. Start with one source-supported target, **VERIFIED: Platinum’s introductory Poké Ball at (128,100)**, and separately validate any gesture needed for reachable tutorial branches. Do not treat the resulting hotspot list as complete. [Intro handler](https://raw.githubusercontent.com/pret/pokeplatinum/main/src/applications/rowan_intro/rowan_intro_app.c)

Before substantial training, require a **human-authored input trace from New Game to the declared endpoint using exactly the proposed actions**. Replay it automatically on the exact target ROM and backend. This establishes that a successful route is expressible independently of whether the agent can discover it.

Retain unrestricted touch for diagnostic runs. Unknown states should produce evidence and an explicit unsupported-state result where detected; a stalled policy alone cannot diagnose missing controls. Disclose RAM-derived masks as privileged state information.

The recommendation would be falsified by any of these findings:

- A required interaction needs arbitrary dragging, moving targets or precision that a small gesture vocabulary cannot reliably cover.
- Required touch occurs in states the gate cannot identify reliably.
- The same input trace diverges after state restoration or across identically configured workers.
- A supposedly sufficient action set cannot replay the complete reference route.
- Measured masked-gesture training offers no practical advantage over a general touch policy.
- A complete physical-button reference trace succeeds for a target title, establishing that touch can be omitted for that benchmark.
