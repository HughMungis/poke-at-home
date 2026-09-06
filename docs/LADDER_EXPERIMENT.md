**Test whether ladder training improves HM01 acquisition from `init.state`, not whether starting closer makes HM01 easier to reach.**

One premise needs reconciliation: `make_ladder.py` lines 6–8 report six HM01 successes in 68 project rollouts, contradicting “every checkpoint plateaus at stage 14.” Audit those records before preregistration. Rare prior successes would make this a reliability experiment rather than a first-ever breakthrough experiment.

1. **Falsifiable hypothesis**

   At a fixed additional training budget of **25 million environment steps**, training with the ladder increases the probability of obtaining HM01 within **260,000 evaluation actions from `init.state` by at least 10 percentage points**, compared with otherwise identical training without ladder starts.

   Define \(\Delta=P_T(\mathrm{HM01})-P_C(\mathrm{HM01})\), averaged across training seeds and evaluation randomness.

   - Evidence of improvement: the 95% confidence interval for \(\Delta\) excludes zero.
   - Evidence for the stipulated practical effect: its lower bound exceeds 0.10.
   - The ≥10-point hypothesis is falsified at this budget if its upper bound is below 0.10.
   - An interval spanning both zero and 0.10 is **inconclusive**, not proof of no benefit.

   A single verified success breaks an observed ceiling; it does not establish that ladder training caused a reliable improvement.

2. **Control and treatment**

   | Component | Control | Treatment |
   |---|---|---|
   | Starting checkpoint | Same frozen checkpoint | Same frozen checkpoint |
   | Additional training | 25 million environment steps | 25 million environment steps |
   | Episode starts | Always `init.state` | `swarm_p=0.75`: 25% initial starts, 75% ladder adoption |
   | Ladder selection | Disabled | `swarm_frontier_p=0.30`, otherwise uniform over files |
   | Save-state pool | None | Fixed, verified 26-state ladder |

   Hold constant rewards—including interaction and map weights—observations, PPO settings, optimizer restoration, worker count, rollout lengths, episode limits, action frequency, emulator version, and checkpoint selection. Pair runs by seed and starting weights; use independent seeds across pairs. Compare equal environment steps, recording wall time separately.

   **Freeze the ladder and disable publishing for this experiment.** Otherwise `_swarm_publish` changes the treatment during training, testing ladder starts plus adaptive sharing. Give each replicate an isolated directory and prevent imports from evaluations.

   Verify all states load and contain no pre-existing HM01. Record hashes and actual start frequencies. Sampling is uniform over **files**, not stages; stage populations therefore affect exposure. The frontier branch selects the first sorted file, not a random deepest-stage file.

3. **Metric and evaluation distribution**

   Primary metric: **fraction of evaluation episodes that newly obtain HM01 before the fixed action limit**. Compute it per trained policy, then average policies equally.

   Detect acquisition directly using the verified HM01 milestone/item state and latch it throughout the episode. Do not infer success from a filename or reward count: `_swarm_publish` adds a popcount delta to the loaded stage, which need not equal the highest milestone reached when flags are skipped or cleared.

   Secondary metrics: maximum latched required-event stage, ticket acquisition rate, HM01 acquisition time with failures treated as censored, and median/IQR of unique map regions. More regions alone does **not** demonstrate crossing the HM01 gate.

   Evaluating from `init.state` **does not invalidate the comparison**: it measures the intended deployment task. Different training distributions are the intervention. With `p=0.75`, treatment also practices that initial state; with `p=1`, early-game retention and transfer become especially uncertain.

   Add a separately reported diagnostic suite starting both policies from identical, preferably held-out stage-14 states. This distinguishes:

   - **Deep-start improvement only:** the agent learned the remaining segment but cannot reliably connect the whole route.
   - **Initial-start improvement:** the curriculum transfers to end-to-end play.

   Do not pool these suites. Use the same evaluation action-selection settings and seed list for both arms, seed policy sampling as well as the environment, and disable swarming during primary evaluation.

4. **Sample size and decision discipline**

   Use **20 independent training-seed pairs, with 50 initial-state evaluation episodes per final policy**: 40 training runs and 2,000 evaluation episodes. This is a concrete starting design, **not a guaranteed power calculation**.

   The 62-versus-31 example demonstrates rollout variability within a checkpoint; it does not estimate variability between independently trained policies. Repeating one checkpoint hundreds of times cannot replace training replicates.

   Run a separate pilot of roughly **5 training pairs × 20 evaluations per policy** to estimate both variance components. Use simulation-based power analysis for the 10-point effect, targeting at least 80% power, and lock the confirmatory sample size before examining its outcomes. Increase the proposed design if needed; rare successes may require substantially more evaluation episodes.

   Analyze paired differences with uncertainty that respects clustering by training run—for example, a paired hierarchical bootstrap. Do not treat 1,000 episodes per arm as 1,000 independent training experiments. Report success counts and confidence intervals, including zero-success outcomes.

   Evaluate the preregistered final checkpoint. Intermediate evaluations are descriptive unless a sequential testing rule was specified beforehand; do not stop at the first favorable result.

5. **Why keep `swarm_p` below 1?**

   At `p=1`, every successful adoption removes an initial-state episode. A pretrained policy can forget early-game behavior, and a policy trained from scratch may never learn it. It can become excellent at finishing supplied situations while remaining unable to reach them from `init.state`. Save-specific parties, inventories, and positions can further limit transfer.

   The code comment that all workers would occupy one identical state is **too strong for this ladder implementation**: random selection across 26 files still supplies diversity. The precise problem is losing initial-state coverage, compounded by concentrated frontier sampling.

   `p=0.75` reserves approximately one quarter of episode starts for practicing the beginning while emphasizing deeper segments. Log realized exposure: configured probabilities do not guarantee coverage, and failed loads can change the mixture. The shown environment defaults to 0.75 but **does not enforce a numerical cap**; any enforced cap must be elsewhere.
