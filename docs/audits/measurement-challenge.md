Both conclusions are **unsupported as stated**. The measurements establish narrow observations; neither establishes the claimed impossibility or causal exclusion.

### 1. “1.06× realtime means training is impossible and broadcasting has no headroom”

**Training impossibility: unsupported. Broadcast headroom: needs qualifying.**

- **This is an emulator microbenchmark, not an environment benchmark.** `with_frame()` cycles the emulator and retrieves a display buffer (lines 66–71). It does not measure observation resizing, normalization, stacking, policy inference, reward computation, or training updates. Forty consecutive memory reads are not a reward function, and that test runs separately from screen extraction. Calling frame extraction “the observation pipeline” overstates what was measured.

- **It also performs some work more frequently than an actual environment might.** Screen extraction and the forty reads happen every emulated frame. If observations and rewards are computed once per action, with an action lasting 24 frames, those costs should occur once per 24 frames. Missing work biases the estimate upward; excessive extraction frequency can bias it downward. This is not a reliable end-to-end bound.

- **Warmup exists, but its adequacy is untested.** The script warms up for 300 frames once, then runs the variants sequentially without restoring a common state. Different variants therefore measure different portions of the boot/title sequence under potentially different host load. The memory test uses only **600 frames**, contradicting the document’s “1800 frames per figure.” Its 67.2 fps exceeding the raw 66.3 fps is evidence that these figures cannot cleanly isolate overhead.

- **There is no representative gameplay workload.** The script neither loads a gameplay save nor supplies input. Whatever boot/title scenes it reaches cannot establish performance in overworld traversal, battles, menus, or transitions. One short measurement per variant on shared cores also cannot characterize contention or sustained performance.

- **Frames are the wrong denominator for the training claim.** Training budgets are expressed in policy decisions or environment transitions. The Game Boy environment takes one action per 24 frames: 2,266 fps corresponds to about **94.4 actions/s**. If the DS used the same repeat, 63.3 fps would correspond to **2.64 actions/s before additional costs**, making ten million transitions roughly **44 days**. That may be impractical for a particular budget; it is not “structurally impossible.” The DS action repeat, learning budget, and acceptable elapsed time must be specified. Nor does this benchmark establish that a GPU fixes the emulator bottleneck.

- **“No headroom” is stronger than the arithmetic.** Relative to 59.826 fps, 63.3 fps is approximately 5.8% throughput headroom—about **0.92 ms per frame**. That is small, unvalidated headroom, not zero. “Any contention” causing failure and slower-than-realtime being “unwatchable” are not measured findings.

**Measurement that would settle it:** Benchmark the actual DS environment and policy at the intended action repeat, using representative gameplay saves. Include preprocessing, reward computation, resets, and training updates; report sustained transitions/s and projected time for an explicit training budget. Separately run the complete broadcast pipeline with encoding and expected competing processes, recording frame deadline misses and sustained playback speed. Repeat both workloads to quantify variability.

### 2. “Heal reward is 1.3% of total return, therefore heal farming does not cause the plateau”

**Unsupported. Even a correct 1.3% figure would not establish that causal conclusion.**

- **The known ID collision invalidates the advertised replication.** Two requested runs yielding one row is not a two-run result. At minimum, run 1’s final metrics were lost. With the shown `setdefault()`/append structure minus the keepalive fix, run 1’s events could also remain while run 2 overwrites its final reward terms, producing a mixed-run record. The surviving 1.3% may describe run 2’s final snapshot; it cannot summarize both runs. The current `_alive` fix does not retroactively validate the earlier output.

- **“Total return” is not what the code demonstrably calculates.** Lines 118–127 divide the final `heal` term by the sum of **positive final reward terms**, excluding negatives. This is not necessarily accumulated episode return, much less discounted return. Establishing equivalence requires checking reward differencing, initial offsets, resets, and scaling. Large earlier progress rewards can dilute a later farming loop to 1.3%.

- **A small aggregate share cannot exclude a local incentive trap.** Healing could provide almost all reward available during the plateau while accounting for little of the whole run. Policy learning depends on rewards available around particular decisions, not merely their fraction of a final total. Conversely, a large share would not by itself prove farming.

- **The checkpoint and exposure may miss the behavior.** The default is the current checkpoint, not necessarily the one observed farming or first entering the plateau. A timed evaluation may terminate before reaching the relevant location, battle, or health configuration. Without coverage evidence, absence of observed farming is an uninformative negative result.

- **The “stationary” detector does not test the full pattern.** It checks only whether the number of discovered tiles stays equal between consecutive positive heal events (lines 122–124). Movement through visited tiles can appear stationary; discovering an occasional tile can hide a repeated farming loop. It does not track damage, HP cycles, battle turns, location, or meaningful progression. It also misses a run containing only one captured heal, and cannot see continuation beyond the evaluation cutoff. Ordinary repeated healing can trigger it too.

**Measurements that would settle it:** First rerun with explicit unique run IDs and assert that completed runs equal reported rows. Evaluate checkpoints known to exhibit the plateau from saves near the suspected exploit, for enough game steps to observe repeated cycles. Persist per-step reward increments, HP changes, battle/location state, and progress; calculate heal reward and time spent specifically within plateau windows. Validate the detector against a known damage–heal loop and a normal healing trajectory.

That establishes whether farming occurs. To establish whether it **causes the plateau**, run replicated, matched training experiments with the exploitable healing incentive removed or capped, comparing progression and loop frequency against the original reward. A final reward percentage cannot substitute for that intervention.
