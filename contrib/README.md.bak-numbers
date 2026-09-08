# Contribute compute

An AI plays Pokemon Red on a live stream every day. This directory is how you can lend it your
spare CPU — on Windows, macOS or Linux, on an Intel/AMD or ARM machine, with or without a GPU.

> **Status: evaluation is live.** Registration and the networked `eval` loop are built and
> tested end to end; the `ladder` job is not, and training is not accepted from contributors
> (see below). The published container image lands on the first CI run — until then, run the
> worker from a checkout. The design and the reasoning are in
> [`../docs/DISTRIBUTED.md`](../docs/DISTRIBUTED.md).

## What you would be donating to

Not "more training" — that is the intuitive answer and it is the wrong one here. The measured
bottleneck is **evaluation**:

| | |
|---|---|
| candidate checkpoints waiting | 56 |
| never scored at all | **27** |
| scored well enough to be promotable (needs 5 runs) | 9 of 32 |
| what the server can score | 3 per night, 1 hour of wall clock per run |

The server is two shared cores that also run the broadcast for 8–12 hours a day. Training more
checkpoints on top of that backlog produces more unscored files, not more knowledge. So the jobs
are offered in this order:

**1. Evaluation** — play one hour with a fixed checkpoint and report what it achieved. CPU only,
no GPU, and it sends back **numbers**, never a binary. This is the job that clears the backlog.

**2. Ladder states** — get past a point in the game the AI cannot reach on its own and contribute
the save state (~167 KB). Training workers then start from varying depths instead of always from
the beginning. This is the highest-value thing you can give us: published research on this
environment reports that **no agent has ever obtained HM01**, which hard-blocks the third gym, and
state-sharing is what got a different project past it.

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

Or, once the image is published:

```bash
docker run --rm \
  -v /path/to/PokemonRed.gb:/app/repo/PokemonRed.gb:ro \
  -v /path/to/init.state:/app/repo/init.state:ro \
  -p 127.0.0.1:7397:7397 \
  -e CONTRIB_TOKEN=<your token> \
  ghcr.io/hughmungis/poke-contrib:latest eval
```

Then open <http://127.0.0.1:7397> for the control panel: how many cores to use, a duty-cycle
slider, when to run, which job types you are willing to take, and a live view of your worker
playing. The panel is served by your own container and is not reachable from outside your
machine — the server never connects to you, your worker pulls work from it.

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
| `worker.py` | the client: `eval` (working), `ladder` *(not built)*, `train` *(not accepted)* |

## Licence

MIT, same as the rest of the repository. `repo/` is a modified fork of PokemonRedExperiments,
also MIT — see [`../NOTICE`](../NOTICE).
