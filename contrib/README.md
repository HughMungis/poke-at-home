# Contribute compute

An AI plays Pokemon Red on a live stream every day. This directory is how you can lend it your
spare CPU — on Windows, macOS or Linux, on an Intel/AMD or ARM machine, with or without a GPU.

> **Status: evaluation and the ladder are live.** Registration, the networked `eval` loop and
> both `ladder` modes are built and tested end to end against the live server, and the container
> image is published. Training is not accepted from contributors (see below). The design and the
> reasoning are in [`../docs/DISTRIBUTED.md`](../docs/DISTRIBUTED.md).

## What you would be donating to

⚠️ **This section said "the bottleneck is evaluation" and, as of 2026-09-08, that is no longer
true.** Continuous evaluation plus an automatic write-off rule cleared it, and the honest numbers
today are:

| | |
|---|---|
| candidate checkpoints on disk | 73 |
| ruled out by provenance (a known-broken experiment) | 26 |
| written off (cannot beat what is live on bad-night rate) | 29 |
| **actually still in play** | **20** |
| never scored at all | 8 |
| runs still owed to judge them all | 75 ≈ 9 days |
| checkpoints scoring near the incumbent | **0** |

That last row is the one that matters. The server can now judge its own backlog in about a week,
and **nothing in it is close to what is already on air** — so more evaluation capacity buys
faster confirmation of "no", not a better broadcast. We would rather tell you that than take your
CPU for something we know is not the constraint.

**What is genuinely stuck is the game itself.** Published work on this environment reports that
**no agent obtained HM01**, which hard-blocks the third gym. Ours has — 10 of the 47 states on the
demonstration ladder carry it, and one is past the departure of the S.S. Anne.

The wall moved rather than fell: **0 of those 47 states has Cut taught**, and the gym is behind a
cuttable tree, so the third badge has still never been won. The ladder is missing exactly three
stages — **11 (Misty)**, **12 (Bill)** and **17 (Lt. Surge)** — and `ladder/next` reports the
current gaps, so you never donate a fifth copy of something the box reaches unaided every night.

The jobs are offered in this order:

**1. Evaluation** — play one hour with a fixed checkpoint and report what it achieved. CPU only,
no GPU, and it sends back **numbers**, never a binary. This is the only job that is fully built
and tested, and it is still useful: contributed runs are **advisory**, ranking which checkpoints
the server spends its own scarce hours on. But see the table above — it is no longer the
bottleneck, so do not expect your hours here to change what is on the stream.

**2. Ladder states** — get past a point in the game the AI cannot reach on its own and contribute
the save state (~167 KB). Training workers then start from varying depths instead of always from
the beginning. This is the highest-value thing you can give us, and right now it is very specific:
**nothing on the ladder has ever learned Cut**, so the third gym has never been opened. A state
from past that point is worth more to this project than any amount of compute, and state-sharing
is what got a different project past its own version of this wall.

```bash
python3 contrib/worker.py ladder --file my.state   # a state YOU produced -- the valuable one
python3 contrib/worker.py ladder --once            # play the on-air checkpoint, donate what it reaches
```

`--file` needs no emulation and takes seconds: play the game yourself, save the emulator state
past a wall the agent cannot get through, and send it. The server does not take your word for how
deep it is — it loads the state into a real emulator and reads the game's own progress flags, so
the depth recorded is the one the game reports. A state that will not load, or that is shallower
than the agent reaches unaided, is refused and told why.

⚠️ **Your emulator must be the same PyBoy the server runs** (2.5.4 — the container pins it).
Save states are version-locked, so a state written by a newer PyBoy will not load on our side and
is rejected rather than silently mis-scored.

**3. Training** — run PPO and produce new checkpoints. Wants a decent core count.

## What you must supply

**A Pokemon Red ROM.** None is included here and none ever will be — it is copyrighted. Dump your
own cartridge. The expected file is `PokemonRed.gb`, 1,048,576 bytes, SHA1
`ea9bcae617fdf159b045185467ae58b2e4a48b9a`. The worker checks that hash and refuses to start
without it, so a wrong file fails immediately instead of quietly producing meaningless results.

**`init.state`**, the save state runs begin from. It is a memory dump of the ROM, so it is not
ours to redistribute either — it ships with the upstream project,
[PWhiddy/PokemonRedExperiments](https://github.com/PWhiddy/PokemonRedExperiments).

## Running it

From a checkout, once you have a token from `/api/contrib/register`:

```bash
export CONTRIB_TOKEN=...
python3 contrib/worker.py --check      # validate before committing an hour
python3 contrib/worker.py eval --once  # one unit, then stop
python3 contrib/worker.py eval         # keep going; Ctrl-C finishes the current unit
```

Or with Docker, which pins the exact versions the server runs:

```bash
docker pull ghcr.io/hughmungis/poke-contrib:latest
docker run --rm \
  -v /path/to/PokemonRed.gb:/app/repo/PokemonRed.gb:ro \
  -v /path/to/init.state:/app/repo/init.state:ro \
  -e CONTRIB_TOKEN=<your token> \
  ghcr.io/hughmungis/poke-contrib:latest eval
```

Any job works the same way — swap `eval` for `ladder`, or mount a state and donate it:

```bash
docker run --rm -v /path/to/my.state:/state:ro -e CONTRIB_TOKEN=<token> \
  ghcr.io/hughmungis/poke-contrib:latest ladder --file /state
```

⚠️ **There is no control panel yet.** An earlier draft of this file described a local web UI on
port 7397; the visualiser was reverted before release and is not in the published client, so
there is nothing listening on that port. The worker prints its progress to the terminal.

⚠️ **Why Docker rather than a pip install.** PyBoy save states are version-locked, and a
checkpoint only loads against the environment it was built for. If your pyboy differs from ours,
a ladder state you spend an evening producing will not load on our side. The image pins the exact
versions the server runs. `contrib/requirements.txt` documents them if you would rather install
natively, but you are then responsible for the drift.

## Is this safe to run?

The container is what we would want you to interrogate, so:

- It never opens a listening port to the internet. It **pulls** work over HTTPS, so there is
  nothing to forward and no inbound firewall rule to get wrong.
- It runs as a non-root user and touches only the directories you mount.
- Your ROM and `init.state` are mounted **read-only** and are never uploaded anywhere.
- Everything it runs is in this repository, MIT licensed, and the image is built by CI from this
  Dockerfile so you can check what went into it.

## Is what I send back trusted blindly?

No, and you should not want it to be. A work unit is `(checkpoint, seed, steps)` and is
**reproducible** — the same unit run twice produces identical results — so results are replicated
across independent machines and compared, and a fraction of units are checkpoints the server has
already scored many times. Contributed scores start out as advisory: they decide which candidates
are worth the server's scarce nightly hours. Results from hosts whose replicas keep agreeing are
promoted to counting directly. This is how BOINC has done it for twenty years; the details and
the one place we had to depart from it are in [`../docs/DISTRIBUTED.md`](../docs/DISTRIBUTED.md).

Nothing a contributor sends can put a model on the stream by itself. Promotion has separate
guardrails — a minimum number of runs, a bad-night rate that has to improve, never while the
broadcast is live, every decision logged and reversible with one command.

## Files here

| file | what it is |
|---|---|
| `Dockerfile` | the contributor image, and the sandbox the server scores untrusted checkpoints in |
| `requirements.txt` | exact pins, taken from the running server rather than from upstream |
| `.dockerignore` | keeps ROMs, save states and secrets out of a published image |
| `worker.py` | the client: `eval` and `ladder` (both working), `train` *(not accepted)* |

## Licence

MIT, same as the rest of the repository. `repo/` is a modified fork of PokemonRedExperiments,
also MIT — see [`../NOTICE`](../NOTICE).
