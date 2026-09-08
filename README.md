# poke@home

An AI plays Pokémon Red on https://youtube.com/@FrankSrirachaGaming at 00:00 UTC every day. This is the client that lets you lend it
your spare CPU — Windows, macOS or Linux, Intel/AMD or ARM, GPU or no GPU.

It is volunteer computing in the shape BOINC and Folding@home established: your machine pulls a
unit of work over HTTPS, computes it, and sends back a result. Nothing listens on a public port.

## Quick start

**Linux / macOS**

```sh
curl -fsSL https://franksriracha.zip/start.sh | sh
```

**Windows (PowerShell)**

```powershell
iex (irm https://franksriracha.zip/start.ps1)
```

Either one clones this repo, checks your Python and your ROM, and prints the command to run next.

**Docker** — no Python setup at all, and it pins the exact versions the server runs (which is
what makes a save state you produce loadable on our side):

```bash
docker pull ghcr.io/hughmungis/poke-contrib:latest
docker run --rm \
  -v /path/to/PokemonRed.gb:/app/repo/PokemonRed.gb:ro \
  -v /path/to/init.state:/app/repo/init.state:ro \
  -e CONTRIB_TOKEN=<your token> \
  ghcr.io/hughmungis/poke-contrib:latest --check
```

Swap `--check` for `eval` or `ladder` once it passes. Your ROM is mounted read-only and never
leaves your machine.

> **Read it before you paste it.** Running a script from someone else's server deserves a
> moment's thought whoever is asking, so these are deliberately short and dull — open
> [start.sh](https://franksriracha.zip/start.sh) or
> [start.ps1](https://franksriracha.zip/start.ps1) and see for yourself. No `sudo` or admin
> rights, nothing installed system-wide, nothing added that runs at boot, and **it does not
> start contributing on its own** — that is always a separate, deliberate command. If you want
> nothing to do with piped scripts, `git clone` this repo and run `python3 contrib/worker.py
> --check`; the script does nothing else.

**You supply the ROM.** None is included here and none ever will be. The worker checks its SHA1
and refuses to start on a wrong file, so a bad copy fails immediately instead of quietly scoring
a different game.

**The client keeps itself current.** On start it asks the server whether it is up to date and
offers to update; decline and it stops without contributing. That is not tidiness — the
environment and its reward terms change as the project learns, so an old client computes a
*different thing under the same name*, and pooling those numbers would corrupt the medians every
promotion decision rests on. The server enforces it too (HTTP 426), rather than trusting each
client to check itself.

> ### Status: eval and the ladder both work; you can contribute today
>
> **Working, tested end to end against the live server:** registration, `--check`,
> `eval --local`, the networked `eval` loop — pull a unit, verify its digest, score it, submit
> the numbers, with results spooled to disk so a dropped connection cannot cost you an hour of
> compute — and both `ladder` modes, including `ladder --file`, which donates a save state you
> produced yourself. The container image is published.
>
> **`train` is not accepted from contributors and may never be** — see below.

## Why this exists

The intuitive answer is "more training", and it is the wrong one here. So, for a while, was
"more evaluation" — continuous scoring plus an automatic write-off rule cleared that backlog, and
the honest position today is:

| | |
|---|---|
| candidate checkpoints on disk | 73 |
| ruled out by provenance, or written off as unable to beat what is live | 55 |
| still in play | 20 |
| **scoring anywhere near what is already on air** | **0** |

The server can now judge its own backlog in about a week, and nothing in it is close to the
checkpoint currently on the stream. More scoring hours buy faster confirmation of "no". We would
rather say that than take your CPU for something we know is not the constraint.

**What is actually stuck is the game.** The
[published study of this environment](https://arxiv.org/abs/2502.19920) reports that no agent
obtained HM01, the item that gates the third gym. Ours has — rarely, and the median run still
stops around the first gym — and the states from those runs are on the demonstration ladder that
training workers start from. **That ladder is the thing worth feeding**, which is why
`ladder --file` (a save state you produced yourself, from somewhere the agent cannot reach) is
the highest-value job on offer, and it costs you seconds rather than an hour.

## What is in here

| path | what it is |
|---|---|
| `contrib/` | the client, the container, and [the setup guide](contrib/README.md) |
| `docs/DISTRIBUTED.md` | the architecture and the reasoning — read this before trusting it |
| `repo/v2/` | the Game Boy environment (modified fork — see Provenance) |
| `eval_checkpoint.py` | the scoring harness |
| `gamereg.py` | game registry: paths, ROM hashes, per-game config |

**Start with [`contrib/README.md`](contrib/README.md).**

## Quick start

```bash
# 1. Get a token. It is shown once and only its hash is stored, so save it.
curl -X POST https://franksriracha.zip/api/contrib/register \
     -H 'Content-Type: application/json' -d '{"handle":"yourname"}'

# 2. Put your own ROM and init.state where the worker expects them (see below),
#    then check the machine before committing an hour to it.
export CONTRIB_TOKEN=...
python3 contrib/worker.py --check

# 3. Take a single unit and stop, so you can see what it does.
python3 contrib/worker.py eval --once

# 4. Once happy, leave it running. Ctrl-C stops it after the current unit.
python3 contrib/worker.py eval

# Or donate a save state instead -- seconds, not an hour, and worth more. See "Why this exists".
python3 contrib/worker.py ladder --file /path/to/my.state
```

A unit is one checkpoint, one seed, a fixed number of steps — about an hour on a typical core.
Progress is printed as it goes, and `/api/contrib/leaderboard` shows who has contributed what.

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
