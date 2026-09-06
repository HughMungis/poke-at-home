# poke-at-home

An AI plays Pokémon Red on a live stream every day. This is the client that lets you lend it
your spare CPU — Windows, macOS or Linux, Intel/AMD or ARM, GPU or no GPU.

It is volunteer computing in the shape BOINC and Folding@home established: your machine pulls a
unit of work over HTTPS, computes it, and sends back a result. Nothing listens on a public port.

> ### Status: not live yet
>
> **What works today:** `worker.py --check` validates a machine, and `worker.py eval --local`
> scores a checkpoint you already have. Both are real and run offline.
>
> **What does not:** the `/api/contrib/*` endpoints are not deployed, so no networked job can
> run and there is nothing to sign up for. The stubs say so rather than silently no-opping.
> Watch the repo rather than the calendar.

## Why this exists

The intuitive answer is "more training". That is the wrong one here, and the numbers are why:

| | |
|---|---|
| candidate checkpoints waiting | 72 |
| never scored at all | **37** |
| scored well enough to be promotable (needs 5 runs) | 9 of 35 |
| what the server can score | ~3 per night, 1 hour of wall clock per run |

The server is two shared cores that also encode the broadcast for eight hours a day. Training
harder on top of that backlog produces more *unscored files*, not more knowledge. **Evaluation is
the bottleneck**, so evaluation is the first job on offer.

The longer-range reason: the [published study of this environment](https://arxiv.org/abs/2502.19920)
reports that no agent obtained HM01, the item that gates the third gym. Our runs have now reached
it six times and taught Cut three times — but that is the best of 129 runs, and the median still
stops around the first gym. Rare success is exactly what more machines produce more of.

## What is in here

| path | what it is |
|---|---|
| `contrib/` | the client, the container, and [the setup guide](contrib/README.md) |
| `docs/DISTRIBUTED.md` | the architecture and the reasoning — read this before trusting it |
| `repo/v2/` | the Game Boy environment (modified fork — see Provenance) |
| `eval_checkpoint.py` | the scoring harness |
| `gamereg.py` | game registry: paths, ROM hashes, per-game config |

**Start with [`contrib/README.md`](contrib/README.md).**

## What you must supply

**Your own Pokémon Red ROM.** None is included here and none ever will be — it is copyrighted.
The client verifies its SHA1 and refuses to start on a mismatch, so a wrong file fails
immediately instead of quietly producing meaningless numbers. `init.state` is a memory dump of
that same ROM and is likewise not ours to redistribute; it ships with the upstream project.

## Is it safe to run?

The point of publishing this is that you can check rather than take our word for it:

- It **pulls** work over HTTPS and never accepts a connection. No port forwarding, no inbound
  firewall rule, and the server never connects to you.
- Your ROM and `init.state` are mounted **read-only** and are never uploaded anywhere.
- It runs as a non-root user and touches only what you mount.
- A work unit is `(checkpoint, seed, steps)` and is reproducible, so results are replicated
  across machines and compared. Contributed scores start out **advisory** — they decide which
  candidates get the server's scarce hours, and nothing a contributor sends can put a model on
  the stream by itself.

**We do not accept trained checkpoints from volunteers**, and that is deliberate: loading one
runs `pickle` over its metadata, which is arbitrary code execution. Evaluation returns numbers
and save states are inert memory dumps we verify by loading them. That asymmetry is the whole
reason the job list is ordered the way it is. The full argument is in
[`docs/DISTRIBUTED.md`](docs/DISTRIBUTED.md), and the short version is in the write-up:
[**We are not running a BOINC server**](https://franksriracha.zip/blog/not-running-boinc).

## Provenance

Everything under `repo/` is a modified fork of
[PokemonRedExperiments](https://github.com/PWhiddy/PokemonRedExperiments) by Peter Whidden, MIT
licensed. The original licence and copyright notice are preserved verbatim at
[`repo/LICENSE`](repo/LICENSE).

`repo/v2/red_gym_env_v2.py` differs from upstream in five ways:

1. **RAM addresses and map layout moved into `gamespec.py`**, so a second game can be supported
   without forking the environment file.
2. **`required_events.json`** — 17 critical-path events, with `required` and `cut` reward terms,
   because upstream's event reward is a flat popcount in which "opened a menu" scores what
   "beat Brock" scores.
3. **`reset()` actually seeds.** Upstream accepted a `seed` argument, assigned it to
   `self.seed`, and never read that value again. Reproducible work units depend on this.
4. **The `required_events` observation is gated** behind a config flag, because adding it changes
   the observation space and makes every existing checkpoint unloadable.
5. **`sound_emulated` is configurable**, to silence a per-tick buffer-overrun log on newer PyBoy.

## Licence

MIT — see [`LICENSE`](LICENSE), which also carries the third-party notice. No ROM, save state, or
other copyrighted game data belongs in this repository.
