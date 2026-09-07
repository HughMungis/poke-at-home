The first distinction to measure is **never reaching the ship, failing to navigate it, or reaching the final interaction and failing to complete it**. Stage 14 and “~70 regions” cannot distinguish these. Neither is evidence of a fixed exploration cap in this code.

Below, times are approximate hands-on costs assuming an existing stage-14 save and a runnable evaluation harness. These are hypotheses, not findings. Missed required-event payouts are excluded given your measurement; healing remains a separate investigation.

### 1. Map-progress shaping stops paying before the ship’s actual bottleneck

**Mechanism.** `map_progress` rewards only increases in the **largest rank ever visited** (lines 1005–1013), not advancement along a route. If S.S. Anne interiors are absent from `gspec.map_progress`, share ranks, or rank below an already-visited optional map, navigation toward HM01 pays no map-progress reward.

**Why here.** The ticket-to-HM01 segment may require several transitions after the last ranked location. Earlier regions could receive useful intermediate payments while this segment gets none. An optional detour can also exhaust later positional rewards prematurely.

**Cheap test — 5–10 minutes.** Dump the actual `gspec.map_progress` table. For the intended route and maps actually visited after the ticket, tabulate:

| Map | Assigned rank | Previous maximum | Actual incremental map reward |
|---|---:|---:|---:|
| Each route/interior map | `rank` or `-1` | `max_map_progress` | `reward_scale × map_weight × max(rank − previous_max, 0)` |

**Supports:** all remaining route transitions pay zero, particularly after an earlier detour. **Kills this mechanism:** the relevant transitions establish successive maxima and produce payouts in the trace.

`update_map_progress()` runs **after** reward calculation, so these payments arrive one action late. Account for that when checking.

### 2. The remaining episode budget is smaller than the remaining task

**Mechanism.** Episodes truncate unconditionally after `max_steps` actions (lines 715–718). Getting the ticket grants no extension. A policy can learn the early game while rarely having enough remaining actions to finish the next segment.

**Why here.** Stages 12–14 describe related Bill interactions; stage 15 is separated by travel, interior navigation, battles, and dialogue. Consecutive stage numbers do not imply comparable task lengths.

**Cheap test — 10–30 minutes.**

- Extract the first ticket time `t14` and remaining actions `R = max_steps − t14` for each successful run.
- From a representative ticket save, manually or script-guidedly obtain HM01 **using the existing `env.step()` actions**. Count actions `L`, including battles and dialogue.
- Compare `R` with `L`. Also continue one original capped rollout beyond its cap with the frozen policy, preserving emulator state, observation history, visitation memory, and recurrent state if applicable.

**Supports:** most episodes have `R < L`, even for competent navigation; or the unchanged policy obtains HM01 shortly after the original cap. **Weakens:** episodes retain many multiples of `L` and spend them looping.

A guided completion is a practical benchmark, **not a proven shortest path**. Failure of an extended policy rollout does not independently kill the horizon hypothesis.

Use the configured action frequency: one action advances `act_freq` emulator frames. The comment mentioning 163,840 steps is not proof of the actual training cap.

### 3. Exploration pays for detours while the necessary route has become unrewarding

**Mechanism.** Exploration pays once per distinct `(x, y, map_id)` per episode (lines 586–595, 959). Necessary revisits pay nothing; fresh optional rooms still pay. There is no explicit “70 maps” saturation threshold.

**Why here.** After the ticket, returning through visited territory can create a long interval with little reward. On the ship, exploring irrelevant rooms may offer more immediate reward than finding and completing the necessary interaction.

**Cheap test — 10–20 minutes.** Over windows before and after the ticket, measure:

- New tiles per 1,000 actions.
- Exploration reward per 1,000 actions.
- Fraction of actions on previously visited tiles.
- Longest interval without positive reward.
- Where newly rewarded tiles occur: required route or optional detours.

Compare those measurements with the guided route from test 2.

**Supports saturation:** novelty collapses after the ticket, with long unrewarded revisits. **Supports diversion:** novelty remains high but comes mainly from detours while necessary transitions are rarely attempted. **Weakens both:** productive navigation continues receiving frequent novelty rewards.

Global-map projection collisions do **not** merge this reward: `seen_coords` includes map identity. They can corrupt the observation, which is a separate hypothesis below.

### 4. The “anti-stuck” term does not penalize sustained loops

**Mechanism.** At 600 visits to a coordinate, the stuck **state score** becomes `−0.05 × reward_scale` (lines 597–604, 965). Since returned reward is the difference of state scores, remaining there costs nothing further. Moving to an unflagged coordinate refunds the penalty.

For a cycle returning to the same stuck-score state, this term sums to zero undiscounted. It is not a recurring inactivity cost.

**Why here.** Early novelty and milestones can break repetitive behavior. Once those become sparse, the environment supplies almost no sustained pressure against revisiting exhausted corridors or repeatedly opening the same dialogue.

**Cheap test — 5–15 minutes.** On a post-ticket loop, log coordinate visit counts and the **difference** of the stuck component. Sum it over complete cycles, and measure how much post-ticket time those cycles occupy.

**Confirms the implementation weakness:** one threshold debit, zero while remaining stuck, and refunds on exit. **Supports it as a relevant contributor:** long loops dominate failed runs. **Kills its relevance:** failures consist of new exploration or a specific interaction failure rather than repetition.

### 5. The map observation aliases ship floors or loses the identity needed at junctions

**Mechanism.** The policy receives no explicit map ID, coordinates, or floor number. Its map input is a centered crop of a global visited-pixel canvas (lines 606–685). Interior mappings could overlap or fall back to shared positions. The visual history contains only three reduced-resolution screens.

**Why here.** Similar-looking interior corridors may require different actions depending on floor or entry history. A centered visitation crop can fail to distinguish them, especially after repeated exploration.

**Cheap test — 15–30 minutes.** First inspect `world.to_global` and the ship map entries for overlaps or fallbacks. Then capture actual observations at a few confusing junctions on different floors, including all observation keys and three-frame histories.

Compare states that require different route actions. Inspect both the full-resolution frame and the policy’s 72×80 image.

**Supports:** different actionable locations produce identical or very similar screens and map crops, with no distinguishing events or history. **Weakens:** floor-specific landmarks remain clear and the actual observations reliably distinguish the junctions.

A projection collision alone does not prove observation insufficiency: screens and event bits might disambiguate it. Likewise, absent explicit floor ID does not prove a feed-forward policy cannot navigate. Check the actual policy’s memory architecture.

### 6. An unobserved inventory or party condition blocks the final segment

**Mechanism.** Observations expose aggregate health and a Fourier encoding of summed levels, but not bag contents/capacity, individual health, moves, status, or party composition (lines 379–387). Relevant details must be recovered through screenshots and menu interaction.

**Why here.** Longer runs can arrive at a new item handoff or battle with materially different inventories and party states despite similar aggregate observations. A full inventory is a concrete candidate to check **if the item dialogue reports it**; the supplied code does not establish the game’s handoff rules.

**Cheap test — 10–20 minutes.** Inspect a failed save’s inventory and party, and record the actual dialogue at the blocked interaction. If it reports a capacity issue, branch that save, free one slot through normal controls, and repeat the interaction. If failure is in battle, record individual HP/status, usable moves, and outcomes.

**Supports:** a specific prerequisite or capacity condition explains repeated failure, and changing only that condition permits progress. **Kills the concrete candidate:** no such blocking condition exists, or the agent never reaches the relevant interaction.

This is distinct from heal farming: the issue is hidden readiness, not positive healing return.

### 7. Fixed button timing prevents reliable interaction or movement

**Mechanism.** Every action presses one button for eight frames, releases it, then waits for the rest of `act_freq` (lines 448–457). There is no explicit neutral action, variable-duration press, or simultaneous-button action.

**Why here.** A particular doorway, facing adjustment, menu, or dialogue sequence could be less tolerant of this timing than earlier tasks. That is a candidate, not evidence that HM01 needs a missing button.

**Cheap test — 15–30 minutes.** Complete the troublesome segment manually through the **seven existing action indices**, with unchanged timing. At a reproducibly failing interaction, replay from the same emulator state using the normal timing and then shorter pulses or inserted neutral frames.

**Kills a hard action-space barrier:** HM01 is obtained using the existing interface. **Supports a timing problem:** the same local interaction consistently fails under existing timing but succeeds with the controlled timing change.

Successful guided play does not kill a policy-discoverability problem, but it removes “the action space cannot do this” from consideration.

### 8. The final milestone is too delayed to compete with immediate rewards

**Mechanism.** There is a crucial correction to the accumulated-reward theory: **early accumulated reward does not directly dilute later payouts here.** `update_reward()` returns differences (lines 695–704). A required-count increase still pays `15 × reward_scale`, regardless of the previous total.

At `reward_scale=0.5` and `explore_weight=0.25`, that is **7.5**, equivalent to **600 new tiles**. The separate Cut reward pays for **knowing the move**, not merely obtaining HM01.

The plausible failure is temporal credit assignment, reward preprocessing, or competing immediate rewards—not a large accumulated denominator in this environment.

**Why here.** The next required payout may be much farther away in actions than Bill’s successive interactions. The JSON contains no separate required milestone between ticket and HM01; generic events and map rewards may or may not fill the gap.

**Cheap test — 15–30 minutes.** Read the actual training configuration and wrappers: discount, GAE parameter, rollout length, reward normalization/clipping, and timeout handling. On the guided trace:

- Measure action gaps between positive rewards and between required milestones.
- Compute `7.5 × gamma**d` at relevant earlier decisions, using actual weights.
- Inspect the milestone reward after preprocessing and compare it with competing rewards over the same future window.
- If available, inspect frozen critic predictions and TD residuals along that trace.

**Supports:** the milestone’s discounted contribution is negligible at the route choices that must lead to it, or preprocessing materially suppresses it. **Weakens:** intermediate rewards bridge the route and the milestone remains substantial at nearby decisions.

A small share of total episode return does **not** confirm this hypothesis. Rollout length alone is not a hard credit horizon because value bootstrapping matters.

### Measurement discipline

Use explicit flag identities for ticket and HM01, not the required-event popcount as a stage number: the environment ignores the JSON’s `"stage"` field when counting progress. That is a telemetry check, not a revival of the missed-latch theory.

For one instrumented continuation, record post-update step, map/coordinates, milestone transitions, reward-component differences, new-tile counts, battle state, and truncation. Existing `agent_stats` retains only 256 entries and mixes current position with previous reward/progress values. It cannot reconstruct a full post-ticket trajectory.

**Best first pass:** audit map ranks, obtain ticket timestamps, and perform one guided HM01 completion through the unchanged action interface. Together, those tests resolve much of the horizon, shaping, action-space, and concrete game-state uncertainty without retraining.
