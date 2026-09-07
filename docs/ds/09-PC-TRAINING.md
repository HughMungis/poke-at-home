**For DS, the Windows desktop must own both training and authoritative evaluation. The ARM server becomes a coordinator and artifact store.** Moving training alone would recreate the existing backlog, with no practical way to score it.

The measurement establishes that this server is unsuitable; it does **not** establish desktop throughput. The RTX 3080 accelerates policy computation, but emulator throughput still depends on the desktop CPU. Benchmark the complete DS environment there, including inference, resets and contention with the existing Game Boy worker, before choosing worker counts or promising training speed.

### What runs where

| Windows desktop | ARM server |
|---|---|
| DS emulator instances, observations, rewards and rollout collection | Run configuration and desired-job records |
| GPU learner and resumable training state | Checkpoint storage, manifests and retention |
| Authoritative DS evaluation and curriculum-state validation | Result ingestion, score history and dashboard |
| Local checkpoint selection for evaluation and durable upload queue | Promotion decision from accepted desktop results, audit log and rollback |
| Locally provisioned ROM and compatible starting states | Health monitoring and alerts |

Use a separate DS worker and environment alongside the existing Game Boy worker. A local resource scheduler should allocate CPU processes, GPU memory and time between them. Start with **scheduled DS training and evaluation windows**, rather than assuming both games and DS evaluation can run concurrently. Pause DS training for evaluation if contention makes parallel execution inefficient.

The desktop should continue its current job during a server outage, retaining checkpoints and results locally for later upload. Training progress must not depend on a network round trip per rollout or episode.

### Checkpoint and result flow

1. **Create an immutable local checkpoint.** Record its hash alongside the environment/code version, emulator build, ROM hash, observation/action/reward versions and training step. Keep full resume state separately if the evaluator only needs policy weights.
2. **Evaluate that exact checkpoint on the desktop.** Use a versioned suite with fixed starting-state hashes, seeds, action/frame-skip configuration and exact step budgets. Record completed steps, termination reason, progress metrics and failures; wall time is a performance metric, not the score budget.
3. **Upload the checkpoint and its result bundle.** The authenticated worker retries interrupted transfers. The server verifies hashes, schema, suite identity and completeness without loading the model or launching an emulator. A result references an immutable checkpoint hash, never “latest.”
4. **Make it eligible only when both are present.** The server compares candidates and incumbent using the same DS suite, applies the DS promotion rule, and records a reversible release pointer. The desktop downloads that pointer if it needs the approved policy.

Save checkpoints more frequently than you perform expensive full evaluations. Use short screening runs to eliminate weak candidates, then spend full-suite compute on promising candidates and incumbent comparisons. Keep screening results separate from promotion evidence.

**Do not reuse the Game Boy hour-budget promotion pool.** Its `budget_min >= 60` admission rule and historical scores do not describe DS performance. DS needs its own evaluation records and promotion criteria. Seeded runs are useful, but cross-machine reproducibility must be demonstrated for this backend; it is not inherited from PyBoy.

### Does volunteer evaluation help?

**Potentially—but not through the current “volunteers rank candidates, server verifies them” design.** That design stops making sense when the server cannot perform the verification.

The server’s 1.06× measurement does not establish volunteer desktop throughput. Capable volunteers could contribute useful aggregate evaluation capacity. However, advisory results only help if they save more authoritative desktop evaluation time than they consume in setup, replication and follow-up checks.

The practical sequence is:

- First build evaluation on the existing trusted desktop.
- If evaluation becomes the measured bottleneck, add another **trusted, sufficiently fast evaluator** using the same job/result contract.
- Consider public volunteers only after measuring available throughput and establishing an effective validation scheme.

For public volunteers, JSON is safe to parse with appropriate validation; it is **not evidence that a run happened honestly**. Replicas, canaries and compatibility classes would still be needed, with canaries and authoritative spot checks produced on trusted desktops. Replication also consumes the scarce compute it is intended to provide.

**Do not build a public DS volunteer platform now.** It is a conditional expansion, not a prerequisite for DS training.

### What stops making sense for DS

- **Server nightly DS scoring and server re-evaluation before promotion:** remove them.
- **Volunteer evaluation as a shortlist for server scoring:** replace the final scorer with the desktop, or omit the volunteer stage.
- **Server-side sandbox evaluation of contributed checkpoints:** a sandbox addresses execution risk, not inadequate throughput. Do not open public DS training uploads now.
- **Server-side emulator validation of contributed ladder states:** validation belongs on a trusted desktop. Do not carry over PyBoy’s state-size, compatibility or load-cost assumptions.
- **Mandatory ARM DS worker packaging:** no demonstrated compute use case justifies it. Build and validate the actual Windows execution path first.
- **Public contribution UI, credits, visualizer and BOINC-like scheduling:** defer them; none accelerates the initial trusted-desktop path.
- **Assumed server DS broadcasting:** treat it as a separate contention-tested decision. At 1.06× there is no established headroom.

The server still owns the project’s durable records and release decisions, but **it no longer independently establishes DS checkpoint quality**. That authority rests on trusted desktop evaluation. A small authenticated job-and-artifact service is enough for this design; the larger public distributed system should remain unbuilt until measured demand justifies it.
