# poke-at-home

An AI plays Pokémon Red on a live stream every day. This is the client that lets you lend it
your spare CPU — Windows, macOS or Linux, Intel/AMD or ARM, GPU or no GPU.

It is volunteer computing in the shape BOINC and Folding@home established: your machine pulls a
unit of work over HTTPS, computes it, and sends back a result. Nothing listens on a public port.

## The third gym has been won exactly once, by a human, in twenty-five minutes

The [published study of this environment](https://arxiv.org/abs/2502.19920) reports that **no
agent obtained HM01**, the item that gates the third gym. Ours does it routinely — the policy on
air reaches the departure of the S.S. Anne as its *median* outcome.

Then it stopped dead for weeks, and the reason turned out not to be the model at all. **In Gen 1,
Cut cannot be used outside battle without the Cascade Badge** (Misty, gym 2). Every save state we
had with Cut taught also had exactly one badge, so the move was **inert** — the agent was standing
at a tree it could never cut, and no amount of training would have changed that. A run forced to
start from those states spent 300,000 steps without once entering Vermilion Gym, which reads
exactly like a policy that is bad at gym 3.

What broke the deadlock was somebody loading one of those saves and playing for **twenty-five
minutes**: Cerulean, beat Misty, walk back, cut the tree, beat Lt. Surge. That state is now in the
ladder, and it is the only one past the third gym that exists.

Since then the loop has started feeding itself — training begins some episodes past the S.S. Anne,
those policies teach Cut during evaluation, the harvest banks those positions, and the ladder gets
deeper:

| | 9 Sep | now |
|---|---|---|
| ladder states | 47 | **86** |
| with Cut taught | 0 | **50** |
| past Lt. Surge | 0 | **1** |

**The frontier is that single state.** Training picks the deepest position it has for roughly a
third of the episodes that adopt one, so every one of those starts in the *identical* spot — which
is precisely the sample-diversity loss the design exists to avoid. **A second and third save from
past the third gym is worth more than any amount of CPU**, and the instructions are
[right below the quick start](#the-one-thing-worth-more-than-any-amount-of-cpu).

Would rather lend CPU? That works too — [Quick start](#quick-start) is right below. Either way
**no ROM is distributed and none ever will be**: you supply your own, and it is checked by hash so
a wrong revision fails immediately instead of quietly measuring a different game.

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

## The one thing worth more than any amount of CPU

Now that it is installed: **play past Lt. Surge and send us the save.**

We have exactly **one** state from the other side of the third gym, and it is the position a third
of all ladder-adopting episodes begin from. A second one is not a duplicate — it is the difference
between every deep episode starting in the same doorway and them starting in different places.

It takes minutes, needs no GPU, and the file is about 167 KB:

```bash
# 1. Play Pokemon Red until you are past Lt. Surge. Further is better -- Rock Tunnel,
#    Lavender, Celadon are all territory no policy has ever reached.
# 2. Send it:
python3 contrib/worker.py ladder --file /path/to/my.state
```

🚨 **It must be PyBoy 2.5.4.** Save states are version-locked and **both directions fail** —
measured against the real ladder, PyBoy 2.7.0 loads **0 of 81** of our states, and it prints only
a "Loading state from an older version" *warning* while doing it, which reads like success.
`contrib/requirements.txt` pins the right version and `worker.py --check` now refuses to proceed
if yours differs. 2.5.4 has no wheel for Python 3.14, so on a 3.14 machine use a 3.13 venv.

**Two other gaps** if you would rather not play that far: the ladder still has nothing for
**Misty** (gym 2) or **meeting Bill**. Misty is the one that matters most — she is the badge that
makes Cut work at all. Ask the box what is short at any moment, since it changes as the agent
improves:

```bash
python3 contrib/worker.py auto      # does whatever is needed now, and says why
```

⚠️ **Send a state you made yourself.** Every upload is verified by loading it in a real emulator
and reading the game's own flags, so a mislabelled file is rejected rather than trusted — but what
makes it worth doing is that a person actually played it.

## Why this exists

The intuitive answer is "more training", and it is the wrong one here. So, for a while, was
"more evaluation" — continuous scoring plus an automatic write-off rule cleared that backlog. The
honest position today:

| | |
|---|---|
| candidate checkpoints on disk | 105 |
| ruled out by provenance, or written off as unable to beat what is live | 65 |
| still in play | 40 |
| scoring at or above what is on air | 5 |

That last row was **0** for weeks, and it only moved once the ladder started working — which it
had not been. Training runs asked for a deep starting position 40% of the time and silently got
`init.state` every single time, because the trainer's PyBoy could not read the server's save
states and the failure path falls back without a word. Those runs looked completely normal and
were plain fine-tuning. The guard that would have caught it counted *files*, not whether one
could be *loaded*; it loads one now.

So evaluation is no longer the constraint, and neither is raw compute.

**What is actually stuck is the game.** The
[published study of this environment](https://arxiv.org/abs/2502.19920) reports that no agent
obtained HM01, the item that gates the third gym. Ours reaches the departure of the S.S. Anne as
its median outcome, and checkpoints trained since the ladder started working now **teach Cut
during evaluation** — a capability the policy on air has never once shown.

But no policy has ever beaten the third gym. The single state from past it was produced by a
person in twenty-five minutes, and it is now the starting position for roughly a third of all
deep training episodes. **That ladder is the thing worth feeding**, which is why `ladder --file`
— a save state you produced yourself, from somewhere the agent cannot reach — is the highest
value job on offer, and costs you seconds rather than an hour.

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
