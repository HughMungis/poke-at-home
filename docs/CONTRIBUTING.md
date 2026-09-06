# Contributing compute

The working job is evaluation: run a fixed model through Pokémon Red and report what it achieved. You need a CPU; a GPU is not required. `ladder` is not built. Training is not accepted from contributors.

Evaluation is the bottleneck. The server can score about 3 runs per night, and a candidate needs at least 5 runs before it can be considered for promotion.

## What runs on your machine

The worker pulls a work unit over HTTPS: one checkpoint, one seed, and a fixed number of steps. The default is 550,000 steps, about an hour on a typical core. The assigned step count determines the work; a faster machine finishes sooner.

The worker downloads the checkpoint, checks its SHA256 digest, and runs one evaluation. It sends back JSON containing the job ID, checkpoint name, seed, step count, and metrics: badges, maps, tiles, events, level totals, required-event progress, and whether the agent knows Cut.

**Evaluation sends back numbers and job identifiers, never files.** Your ROM, `init.state`, and model files are not uploaded.

The worker pulls work; the server never connects to your machine. No port forwarding or inbound firewall rule is needed.

Checkpoint downloads are about 14 MB each, and the cache retains up to 3. Completed results are written to `contrib/unsent/` before submission. A dropped connection leaves them there for a later retry.

A matching download digest proves that a checkpoint arrived intact. It does not prove that it is safe: loading a checkpoint can execute code through its metadata. Running the worker means trusting the project that supplies those checkpoints.

## Supply the game files

You must supply your own Pokémon Red ROM, dumped from your cartridge:

| File | Expected value |
|---|---|
| `PokemonRed.gb` | 1,048,576 bytes |
| SHA1 | `ea9bcae617fdf159b045185467ae58b2e4a48b9a` |

No ROM is distributed because it is copyrighted. The worker checks the hash and refuses to run on a mismatch. A different revision can produce plausible scores that measure a different game.

You also need `init.state`, the starting save state. It contains a memory dump of the game and is not ours to redistribute. The setup guide identifies the upstream project that supplies it.

The documented layout places both files under `repo/`. Run `--check` to confirm the paths your copy expects.

## Install and get a token

Run these commands from the repository root: the directory containing `gamereg.py`, `eval_checkpoint.py`, and `contrib/`.

Use a Python virtual environment and install the pinned dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r contrib/requirements.txt
```

On Windows PowerShell, activate it with `.venv\Scripts\Activate.ps1`.

Register a handle:

```bash
curl -X POST https://franksriracha.zip/api/contrib/register \
  -H 'Content-Type: application/json' \
  -d '{"handle":"yourname"}'
```

Save the returned token. It is shown once; the server stores only its hash. Set it in the terminal where you will run the worker:

```bash
export CONTRIB_TOKEN='your-token'
```

On Windows PowerShell:

```powershell
$env:CONTRIB_TOKEN = 'your-token'
```

Keep the token out of commits, screenshots, and issue reports.

## Check before committing an hour

```bash
python3 contrib/worker.py --check
```

This checks the ROM hash, presence of `init.state`, and dependency imports. It prints dependency versions and the logical CPU count. Fix every `!!` item before running work.

There are limits to this check:

- It reports whether a token is set; it does not test whether the server accepts it. A missing token does not fail the check because local evaluation needs none.
- It checks that `init.state` exists, not that the emulator can load it.
- It reports installed dependency versions; it does not enforce the pins in `contrib/requirements.txt`.

If you already have a trusted, compatible checkpoint, run a short local evaluation to exercise model loading and the emulator:

```bash
python3 contrib/worker.py eval --local /absolute/path/to/checkpoint.zip \
  --seed 1 --steps 1000 --runs 1
```

This submits nothing. A 1,000-step run checks that evaluation starts and finishes; it is not a full score.

Then take one networked unit:

```bash
python3 contrib/worker.py eval --once
```

Check the printed checkpoint, seed, assigned steps, completion metrics, and submission response. This run takes the full assigned step count. If no work is available, `--once` exits without evaluating anything.

Once that works, keep taking units:

```bash
python3 contrib/worker.py eval
```

## What happens to your result

Completed results are saved locally, then submitted. Network failures, server errors, and rate limits defer submission for a retry. Most other HTTP 4xx responses are treated as permanent rejection, and the local result is discarded; read the submission output.

**Contributed results are ADVISORY. They cannot promote a model by themselves.** They help decide which candidates deserve the server's limited evaluation time.

The design calls for comparing replicas and using known checkpoints to assess agreement between machines. Submission alone is not proof that those checks have passed, and it does not grant promotion authority.

This separation is deliberate. A volunteer machine can be misconfigured, run stale code, or report invented numbers. Promotion has separate requirements, including enough runs, an improved bad-night rate, and no promotion during a live broadcast. Decisions must be logged and reversible.

The server does not accept trained checkpoints from volunteers. Loading their metadata can execute arbitrary code. Numeric evaluation results give the server something it can check without loading a contributor's model.

See [the distributed-computing design](docs/DISTRIBUTED.md) for the reasoning.

## Stop

Press **Ctrl-C once** to finish the current unit, attempt submission, and stop. This can take the remainder of the run.

Press **Ctrl-C again** to abandon the current unit immediately. Incomplete work is discarded.

To stop automatically after a fixed number of completed units:

```bash
python3 contrib/worker.py eval --max-units 3
```

Completed results awaiting submission remain in `contrib/unsent/`; keep that directory so the next networked run can retry them.

Docker's default 10-second stop timeout can kill the worker before a unit finishes. That discards the unfinished work.

## Troubleshooting

### The worker finishes, but the results are too short to count

A stale client has silently produced evaluations shorter than the required run. A successful process exit, plausible metrics, or a submission message does not establish that the full evaluation happened.

Update the whole repository, including `eval_checkpoint.py` and the environment code under `repo/v2/`. Replacing only `contrib/worker.py` leaves the scoring code stale.

In a git checkout, inspect local changes before updating:

```bash
git status
git pull --ff-only
```

For a ZIP download, extract a fresh copy. Preserve your game files and any unsent results, and make sure you launch the worker from the new directory.

Reinstall the pinned dependencies, rerun `--check`, and try one unit. The current worker passes the assigned step count to the evaluator with no wall-clock cutoff. Do not edit a short result's reported step count to make it count.

### Paths work in a checkout but fail in a ZIP download

A git checkout may be named `poke-at-home`; an extracted ZIP may be named `poke-at-home-main` or sit inside another directory. Commands that assume one folder name can point at the wrong copy.

Find the directory containing `gamereg.py`, `eval_checkpoint.py`, and `contrib/`, then run commands from there:

```bash
python3 contrib/worker.py --check
```

Use the missing-file paths printed by the check to place the ROM and `init.state`. Do not assume that extracting them beside the ZIP puts them where the worker expects.

For local evaluation, use an absolute checkpoint path. Relative checkpoint paths are resolved against the repository root, and evaluation changes its working directory to `repo/v2/`.

If you set `CONTRIB_CACHE` or `CONTRIB_SPOOL`, use absolute paths for those too.

### Dependencies import, but evaluation cannot load the state or model

Compare the versions printed by `--check` with `contrib/requirements.txt`. PyBoy save states depend on the emulator version, and checkpoints depend on the environment's observation space.

Install the repository's pinned dependencies in your virtual environment. Passing the import checks alone does not establish compatibility.
