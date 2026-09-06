# Distributed contribution — architecture and the decisions behind it

How volunteers donate compute to this project, why it is shaped the way it is, and the two places
where the obvious design is wrong.

Contributor-facing instructions live in [`../contrib/README.md`](../contrib/README.md). This file
is the reasoning.

## The premise, and the measurement that reshaped it

The intuitive version is "more people training means a better model sooner". Measured on the
server, that is not where the constraint is:

| | |
|---|---|
| candidates on disk | 56 |
| **never scored at all** | **27** |
| checkpoints with the 5 runs promotion requires | 9 of 32 |
| server eval throughput | 3 checkpoints/night, **1 hour of wall clock per run** |

That is ~9 nights to score the backlog once and ~15 to make it promotable — from a single
contributor. Adding volunteer *training* first produces more unscored files. **Evaluation is the
bottleneck, and it is also the only one of the three jobs that is safe to hand to strangers**,
because it returns numbers rather than a binary.

Order: **evaluation → ladder states → training.**

## Prior art: what BOINC and Folding@home actually do

Worth being precise, because the two are different projects with different models and we want
pieces of both. **BOINC is the Berkeley one** (SETI@home's infrastructure, now Einstein@home,
Rosetta@home). **Folding@home is Stanford.**

**BOINC server** is six daemons around a MySQL database: *work generator*, *feeder/scheduler*,
*transitioner* (decides what needs more replicas or a resend), *validator* (compares replicated
results), *assimilator* (files accepted results), *file deleter*. Only the validator and
assimilator are written by the project; the rest ship with BOINC.

**Folding@home** separates an *assignment server* from *work servers*, and configures its client
through **Web Control** — a browser UI on `127.0.0.1` with a folding power slider — plus a
separate viewer for the molecule.

| their concept | ours |
|---|---|
| work generator | the 27 unscored candidates are already the queue |
| assignment/scheduler | `/api/contrib/*/next`, modelled on the existing `/api/art/next` |
| **validator** | 🚨 cannot be copied as-is — see below |
| assimilator | `auto_promote.all_runs()` already pools runs per checkpoint |
| file deleter | candidate retention |
| credit / teams | leaderboard on `/poke` |
| client preferences | the local web panel |
| screensaver / graphics API | the visualizer |
| `docker_wrapper` | the container |

### 🚨 Where we had to depart from BOINC: the validator

BOINC validates by sending a work unit to N hosts and **comparing the results for equality**.
That works because the computation is deterministic. Ours was not, in two separate ways:

1. **Deliberate policy sampling.** `eval_checkpoint.py` calls `model.predict(deterministic=False)`
   because evaluating deterministically would measure a policy the stream never runs. The
   variance is large — the same checkpoint scored **62 maps in one run and 31 in the next**.
2. **Nothing was seeded at all.** There was no `set_random_seed` anywhere in the eval, and
   `red_gym_env_v2.reset()` did `self.seed = seed` and never read the value again — so the env's
   only RNG (`np_random`, which drives swarm adoption) was seeded by the OS every time.

**Fixed 2026-09-05.** `eval_checkpoint.py --seed` seeds python/numpy/torch per run and passes the
seed to `reset()`, which now calls `super().reset(seed=seed)`. Verified: the same seed reproduces
metrics exactly, a different seed diverges.

⚠️ **A seed alone is not enough, and this is the subtle half.** The run loop was bounded by
**wall clock**, so the same seed on a fast host and a slow host executes a different number of
steps and diverges anyway. `--exact-steps` bounds a run by step count instead. **A reproducible
work unit is `(checkpoint, seed, steps)`** — all three.

⚠️ The nightly server eval deliberately keeps using the **time** budget, so its score history
stays comparable with everything recorded before this change. A step-exact run records
`budget_min: 0.0`, which excludes it from `auto_promote`'s `>= 60.0` pool by construction rather
than being silently averaged in with the hour-long runs.

⚠️ Seeding does not survive a change of **architecture** — float operations reorder. BOINC already
names the fix: *homogeneous redundancy*, i.e. only compare replicas from hosts of the same class.
Compare amd64 against amd64. Where classes must be mixed, fall back to a statistical test rather
than exact match.

### Should we just run a real BOINC project? No

- BOINC's documented server minimum is **8 GB RAM and 40 GB disk**, plus LAMP, MySQL and six
  daemons. This server has 11 GB total with ~7 GB free while broadcasting. It would fit only by
  displacing the thing it exists to run.
- BOINC's model is that **the project distributes the application and its input files**. Our input
  is a copyrighted ROM we can never distribute. `docker_wrapper` mounts the slot and project
  directories; there is no documented mechanism for a volunteer-supplied local input.
- BOINC's volunteers attach to projects because they are **science**. A Pokemon project would be
  contentious there, and this box's own BOINC client is tolerated on exactly that framing.

**So: borrow the architecture, not the implementation.** Every client-side feature worth having is
reproducible in a small local web UI, and if a BOINC front end is ever wanted, `docker_wrapper`
means the container is already the right artifact.

## Security model

### 🚨 A checkpoint is executable code

`stable_baselines3/common/save_util.py:165` calls `cloudpickle.loads()` on any `:serialized:` key
in a checkpoint's `data` blob. `custom_objects` only short-circuits the keys it names
(`lr_schedule`, `clip_range`), so `policy_class` and the observation/action spaces still
deserialise. The tensors are safe (`th.load(..., weights_only=True)`) — the **metadata is not**.

`eval_checkpoint.py` and `nightly.py` both call `PPO.load` as `ubuntu`, which has passwordless
sudo. **Scoring a checkpoint from a stranger, as the pipeline stands, is remote root.**

So, by job:

| job | what crosses the wire | handling |
|---|---|---|
| eval | JSON numbers | safe by construction; no binary is accepted |
| ladder state | ~167 KB PyBoy memory dump | inert bytes, and `make_ladder.classify()` verifies by **loading it into a real PyBoy and reading the game's own flags** — a fabricated state either fails to load or classifies honestly |
| training | ~14 MB checkpoint | **quarantined**: scored only inside the contributor container with `--network none --read-only --cap-drop ALL`, non-root, pids/memory limits, ROM and state mounted read-only, tmpfs scratch. Only the JSON on stdout comes back |

🔑 **The contributor image and the sandbox image are the same image.** One artifact, two uses — so
the sandbox is exercised continuously by real contributors rather than being a path that only
runs on hostile input.

⚠️ Stated honestly: a container is not a security boundary against a determined kernel exploit. It
moves an attacker from *"calls `PPO.load` and is root"* to *"needs a kernel or Docker
vulnerability"*. That is a real improvement and not a guarantee.

### Trust, and why fabricated results cannot reach the stream

Contributed scores are **advisory first**: they rank which 3 of 27 candidates deserve the
server's scarce nightly hours. That requires zero trust and is useful on day one, because the
server currently picks essentially arbitrarily. Hosts earn quorum trust through replica agreement
and canary units (checkpoints already scored many times on the server); trusted hosts' runs are
then pooled into the promotion statistics.

Underneath all of it, `auto_promote.py`'s existing guardrails are unchanged: a minimum of 5 runs,
bad-night rate ranked ahead of median, a margin requirement, never while the broadcast is live,
and every promotion logged and reversible with one command.

### The endpoint boundary

🔑 **`/api/train/*` is not opened.** It stays exactly as it is — the single-token path the
project's own training PC depends on. Everything public goes in a new **`/api/contrib/*`** family
with per-contributor credentials, so a mistake in new code cannot reach the existing path.

Before anything opens, `/api/train/upload`'s ingest needs hardening regardless: it buffers up to
**512 MiB in RAM** per request with unbounded threads and no rate limit of any kind, and
`log_message` is disabled so failed auth is silent and unlogged.

## Packaging

**Docker, multi-arch amd64 + arm64, built by CI and published to GHCR.**

⚠️ Not built on the server: qemu amd64 emulation there has been measured at **9+ minutes for a
`steamcmd` no-op**, so cross-building locally is not credible. The repository is public on GitHub,
so Actions runners are free.

⚠️ **Version pinning is load-bearing, not hygiene.** PyBoy save states are version-locked, and a
checkpoint only loads against the observation space it was built for — we have hit "Observation
spaces do not match" twice with a single game. `contrib/requirements.txt` is pinned to what the
server actually runs, **not** to `repo/v2/requirements.txt`, which is upstream's and is stale on
every line that matters while also pulling ~2.9 GB of CUDA.

## Adoption

This is the actual risk, not the engineering. Both reference projects lean on the same two
things, so we do too:

- **A local control panel** (Folding@home's Web Control): cores, duty cycle, schedule, job types.
  ⚠️ Idle- and battery-detection are per-OS; the portable controls come first and idle detection
  is a later per-platform extra rather than something promised up front.
- **A visualizer.** 🔑 Folding@home had to make a protein look interesting. **Our compute output is
  literally a Game Boy screen** — a contributor's screensaver is their own machine playing
  Pokemon, with the checkpoint, seed, badges and progress on it. The rendering already exists in
  `nightly.py` (PyBoy → frames → PIL overlay). Shipping it as a stream on the container's
  localhost port makes it a full-screen browser tab or wallpaper source on every OS at once.
- **Credit**: eval-hours donated, ladder stages first reached with the finder's name, checkpoints
  promoted.

## Honest expectations

**The published ceiling has been beaten here — which sharpens the argument rather than removing
it.** [arXiv:2502.19920](https://arxiv.org/abs/2502.19920) studies this exact environment and
reports no agent obtaining HM01, the gate on the third gym. Our own eval history has **6 runs
reaching HM01 and 3 that actually taught Cut**.

⚠️ But those are the best of 68 stochastic runs; the median still stops around Brock. So the
original point stands in a more useful form: more contributors sampling the same distribution
faster does not change its *shape*. What changes the shape is starting later runs from the states
those rare successes reached — **which is the ladder**, and is the real argument for ranking state
contribution above training. Since 2026-09-05 the continuous eval harvests exactly those states
(`eval_checkpoint.py --harvest` → `make_ladder.py`) instead of discarding them.

**Distributed eval multiplies the server's aim, not its capacity**, until quorum-earned trust
lets contributed runs count directly.

## Status

| phase | state |
|---|---|
| Eval seeding + step-exact units | ✅ done, verified 2026-09-05 |
| Ingest hardening (rate limit, streaming upload, logging) | not started |
| Container + `worker.py` | scaffolded here; client not written |
| `/api/contrib/*` endpoints | not started |
| Local control panel | not started |
| Visualizer | not started |
| Quarantined training uploads | not started |

Full plan: `~/.claude/plans/cozy-foraging-charm.md`.

## Sources

- [BOINC server cookbook](https://github.com/BOINC/boinc/wiki/Create-a-BOINC-server-(cookbook))
- [BOINC ServerIntro — hardware requirements](https://github.com/BOINC/boinc/wiki/ServerIntro)
- [BOINC result management (validator / assimilator)](https://wiki.debian.org/BOINC/ServerGuide/ResultManagement)
- [BOINC preferences](https://github.com/BOINC/boinc/wiki/Preferences) ·
  [screensaver logic](https://github.com/BOINC/boinc/wiki/ScreensaverLogic)
- [BOINC Docker apps / `docker_wrapper`](https://github.com/BOINC/boinc/wiki/Docker-app-implementation)
- [Folding@home servers](https://foldingathome.org/faq/running/) ·
  [Web Control](https://client.foldingathome.org/) ·
  [power slider](https://client.foldingathome.org/)
