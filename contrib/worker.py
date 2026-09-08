#!/usr/bin/env python3
"""The contributor client. Runs inside the container; pulls work, never accepts a connection.

  python3 worker.py --check              # validate this machine before donating anything
  python3 worker.py eval --local <ckpt>  # score a checkpoint you already have, no server
  python3 worker.py eval --once          # take ONE unit from the box and stop
  python3 worker.py eval                 # keep taking eval work until interrupted
  python3 worker.py ladder               # play the best checkpoint, donate the deep states
  python3 worker.py ladder --file X.state  # donate a save state YOU produced  <-- most valuable
  python3 worker.py train                # PPO, upload candidates        [not accepted -- see below]

🔑 PULL, NEVER PUSH. The contributor's machine asks the box for work over HTTPS. Nothing
listens on a public port, so there is no forwarding to set up and no inbound rule to get wrong.

⚠️ STATUS: everything above is real except `train`, which is deliberately NOT accepted from
contributors and may never be: loading a checkpoint runs pickle over its metadata, which is
arbitrary code execution, so the server takes numbers and save states -- things it can verify --
and not executable code. A stub that announces itself is honest; one that silently no-ops
wastes a contributor's evening. See docs/DISTRIBUTED.md.
"""
import argparse
import hashlib
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # repo root: gamereg.py, eval_checkpoint.py live here
sys.path.insert(0, ROOT)

BOX = os.environ.get("CONTRIB_BOX", "https://franksriracha.zip")
TOKEN = os.environ.get("CONTRIB_TOKEN", "")
GAME = os.environ.get("CONTRIB_GAME", "red")

# One hour of wall clock measures ~570k steps on the server. A work unit is bounded by STEPS,
# not time, so that two machines of different speeds compute the same thing -- see check().
DEFAULT_UNIT_STEPS = 550_000

# Downloaded checkpoints are kept so the same one handed out twice is not fetched twice; results
# that could not be submitted are kept so an hour of compute is never lost to a flaky network.
CACHE_DIR = os.environ.get("CONTRIB_CACHE", os.path.join(HERE, "ckpt-cache"))
SPOOL_DIR = os.environ.get("CONTRIB_SPOOL", os.path.join(HERE, "unsent"))
IDLE_SLEEP = 300        # nothing to score: wait rather than hammer the box
CACHE_KEEP = 3          # checkpoints to retain; each is ~14 MB

# ---- ladder ------------------------------------------------------------------------------
# A ladder run is NOT scored, so -- unlike an eval unit -- this number does not have to match
# anyone else's. It is purely "how long am I willing to play for", and longer is strictly
# better: states are harvested DURING the run, each time the agent reaches a new stage, so a
# run that goes twice as far banks the deeper rungs that are the whole point. One hour is the
# default only because it is the smallest amount of time worth asking for.
LADDER_STEPS = int(os.environ.get("CONTRIB_LADDER_STEPS", str(DEFAULT_UNIT_STEPS)))
# 🚨 eval_checkpoint.HARVEST_DIR defaults to a path beside the SERVER's copy of the harness,
# which is not where a contributor's writable space is (in the container it is /app, owned by
# root outside the mounts). The ladder job overrides it to this, next to the cache and the
# spool, so the states land somewhere the contributor can see and keep.
# ⚠️ Absolute HERE, at import. A ladder run chdirs into repo/v2 before handing this to the
# harness, so a relative path would be resolved against a different directory there than in the
# scan afterwards -- states would be written somewhere the upload step never looks.
HARVEST_DIR = os.path.abspath(
    os.environ.get("CONTRIB_HARVEST", os.path.join(HERE, "ladder-harvest")))
# The published contributor image. Named here because a stale client running inside it cannot
# update itself -- see enforce_version().
CONTRIB_IMAGE = os.environ.get("CONTRIB_IMAGE", "ghcr.io/hughmungis/poke-contrib:latest")

# Set by SIGINT/SIGTERM. Checked BETWEEN units only -- a unit takes about an hour and there is no
# safe way to abandon one mid-flight and still report an honest number, so the loop finishes what
# it started. Docker's 10-second SIGKILL will cut a unit short; nothing is corrupted when it does,
# the work is simply discarded.
_STOP = False


def _on_signal(signum, frame):
    global _STOP
    _STOP = True
    print("\n  stopping after this work unit (press again to abandon it)")
    signal.signal(signum, signal.SIG_DFL)      # a second one kills immediately


def _ok(msg):
    print(f"  OK  {msg}")


def _bad(msg):
    print(f"  !!  {msg}")


# ---- version + self-update ---------------------------------------------------------------
# 🔑 WHY A STALE CLIENT IS REFUSED RATHER THAN NAGGED. Contributed results are only worth
# anything if every machine computed the SAME thing. The environment, its reward terms and the
# work-unit definition all change as this project learns -- a client from two weeks ago scoring
# against an older reward does not produce a slightly-out-of-date number, it produces a number
# that cannot be compared to any other, and pooling it silently corrupts the medians every
# promotion decision rests on. Refusing is the honest outcome; a warning that can be ignored
# would let one stale volunteer quietly poison the pool for everyone.
#
# ⚠️ Deliberately a PROMPT, never a silent replacement. Software that rewrites itself without
# asking is indistinguishable from something you would not want on your machine, and asking
# costs one keypress. --yes accepts in advance for unattended runs.
CLIENT_VERSION = 1


def _fetch_version():
    """{version, sha256, notes} from the box, or None if it cannot be reached."""
    try:
        with urllib.request.urlopen(BOX.rstrip("/") + "/api/contrib/version", timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _is_git_checkout():
    return os.path.isdir(os.path.join(ROOT, ".git"))


def _in_container():
    """True when running inside Docker/containerd.

    🚨 THIS DECIDES WHETHER THERE IS ANY UPDATE PATH AT ALL. The published image has no .git and
    no git binary, so a containerised contributor cannot pull, and even if they could the change
    would live in a layer that `docker run --rm` throws away -- they would be told to update, do
    it, and be told again on the next run. Without this branch every container dead-ends at the
    first version bump with advice it cannot follow.
    """
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8") as f:
            blob = f.read()
    except OSError:
        return False                  # not Linux, or no procfs: assume a normal host
    return "docker" in blob or "containerd" in blob


def enforce_version(assume_yes=False, offline_ok=True):
    """Refuse to contribute on a stale client. Returns True if it is safe to continue.

    ⚠️ Unreachable box is NOT treated as stale. Refusing to run because the network hiccuped
    would turn every blip into a support question, and a client that cannot reach the box has
    nothing to submit anyway -- the work loop will fail on its own terms, with a better message.
    """
    info = _fetch_version()
    if info is None:
        if offline_ok:
            print("  (could not reach the box to check for updates; continuing)")
            return True
        return False
    latest = int(info.get("version", 0))
    if CLIENT_VERSION >= latest:
        return True

    print("")
    print(f"  This client is version {CLIENT_VERSION}; the box is running {latest}.")
    for n in info.get("notes", [])[:4]:
        print(f"    - {n}")
    print("")
    print("  Results from a stale client cannot be pooled with everyone else's -- the")
    print("  environment and its reward terms change, so an old client computes a different")
    print("  thing under the same name. It will not be accepted.")
    print("")

    # ⚠️ Answered BEFORE the prompt, not after it. In a container the answer to "update now?"
    # is always "I cannot", and the useful instruction is the pull command -- which the
    # contributor would never see, because `docker run` without -it has no stdin and input()
    # raises EOFError straight into the "not updating" path.
    if _in_container():
        print("  This is the container image, which cannot update itself. Pull a new one and")
        print("  re-run the same command:")
        print(f"    docker pull {CONTRIB_IMAGE}")
        print("")
        print("  Not contributing until then. Nothing on your machine was changed.")
        return False

    if not assume_yes:
        try:
            ans = input("  Update now? [Y/n] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("", "y", "yes"):
            print("")
            print("  Not updating, so not contributing. Nothing was changed on your machine.")
            print("  Re-run when you are ready to update.")
            return False

    if _is_git_checkout():
        print("  Updating (git pull)...")
        rc = os.system(f'git -C "{ROOT}" pull --ff-only')
        if rc != 0:
            print("")
            print("  git pull failed -- most likely local changes in the checkout.")
            print(f"  Fix that by hand in {ROOT}, then re-run.")
            return False
    else:
        print("")
        print("  This is not a git checkout, so it cannot update itself safely.")
        print("  Re-run the quick-start command to get a current copy:")
        print("    https://franksriracha.zip/start")
        return False

    # 🚨 RE-EXEC rather than carrying on. The freshly pulled worker.py is on disk but THIS
    # process is still running the old code, and the whole point was not to compute under it.
    print("  Updated. Restarting with the new client...")
    sys.stdout.flush()
    os.execv(sys.executable, [sys.executable] + sys.argv)
    return False        # not reached


def check():
    """Validate everything BEFORE a contributor commits hours to a run.

    Modelled on train_worker.py --check, with one addition that matters more here: the ROM hash.
    A contributor supplies their own ROM, and a different revision produces scores that look
    entirely ordinary while measuring a different game.
    """
    import gamereg
    ok = True
    print("== identity ==")
    print(f"  box   {BOX}")
    print(f"  game  {GAME}")
    if TOKEN:
        _ok("CONTRIB_TOKEN is set")
    else:
        # Deliberately NOT _bad(): `--local` needs no token, so flagging this as a failure while
        # then printing "ALL CHECKS PASSED" would be telling the contributor two different things.
        print("  --  CONTRIB_TOKEN not set (needed only for networked jobs; --local works without)")

    print("\n== game files ==")
    try:
        g = gamereg.get(GAME)
    except KeyError as e:
        _bad(str(e))
        return 1
    good, detail = g.verify_rom()
    if good and g.rom_sha1 and detail == g.rom_sha1:
        _ok(f"ROM verified ({g.rom} sha1 {detail[:12]}...)")
    elif good:
        _bad(f"ROM present but {detail}")
    else:
        # 🚨 Hard failure. Running on the wrong ROM is worse than not running: it produces
        # plausible numbers that quietly poison the score table.
        _bad(f"{detail}")
        _bad("mount your own ROM read-only at " + g.rom_path())
        ok = False
    st = os.path.join(g.repo, g.init_state)
    (_ok if os.path.isfile(st) else _bad)(
        f"init.state {'found' if os.path.isfile(st) else 'MISSING at ' + st}")
    ok = ok and os.path.isfile(st)

    print("\n== dependencies ==")
    # ⚠️ Versions are reported, not just presence. PyBoy save states are version-locked and a
    # checkpoint only loads against its own observation space, so a mismatch here is the
    # difference between a contribution that counts and one that cannot be read.
    import importlib.metadata as md
    for mod in ("pyboy", "torch", "stable_baselines3", "gymnasium", "numpy"):
        try:
            __import__(mod)
            # ⚠️ Via importlib.metadata, NOT module.__version__: pyboy exposes no __version__
            # attribute at all, and pyboy's version is precisely the one that must be reported
            # because save states are version-locked to it.
            try:
                ver = md.version(mod)
            except Exception:
                ver = getattr(sys.modules[mod], "__version__", "unknown")
            _ok(f"{mod} {ver}")
        except Exception as e:
            _bad(f"{mod}: {e}")
            ok = False

    print("\n== sizing ==")
    n = os.cpu_count() or 1
    print(f"  {n} logical CPU(s). One work unit is ~{DEFAULT_UNIT_STEPS:,} steps "
          f"(about an hour on a typical core).")

    print("\n" + ("ALL CHECKS PASSED" if ok else "FIX THE !! ITEMS FIRST"))
    return 0 if ok else 1


def eval_local(ckpt, seed, steps, runs):
    """Score a checkpoint on this machine and print the result. No server involved.

    This is the whole eval job minus the network, so it is also the way to prove a contributor's
    setup produces sane numbers before any of it counts for anything.
    """
    import gamereg
    g = gamereg.get(GAME)
    good, detail = g.verify_rom()
    if not good:
        print(f"refusing to run: {detail}")
        return 1
    sys.path.insert(0, os.path.abspath(g.v2))
    os.chdir(g.v2)
    import eval_checkpoint as ec
    ec.GAME = GAME
    if not os.path.isabs(ckpt):
        ckpt = os.path.join(ROOT, ckpt)
    # budget_s=None => bounded by STEPS, which is what makes the result reproducible. Combined
    # with the seed, another machine of the same architecture can re-derive it exactly.
    entry = ec.evaluate(ckpt, runs, None, steps, ec.map_names(), seed=seed)
    print(f"\nseed={seed} steps={steps:,} runs={runs}")
    print(f"median: {entry['median']}")
    print(f"best:   {entry['best']}")
    return 0


def _api(path, method="GET", body=None, timeout=120, raw=False, blob=None):
    """One call to the box, carrying the contributor token. Returns parsed JSON, or bytes if raw.

    `body` is JSON-encoded; `blob` sends bytes verbatim, which is what the ladder endpoint takes
    -- a save state is 167 KB of inert memory dump and base64ing it into JSON would grow it by a
    third to no purpose.

    Raises on transport failure so the caller can decide whether to retry; the loop treats a
    network error as "wait and try again", never as "this unit failed".
    """
    url = BOX.rstrip("/") + path
    data = blob if blob is not None else (json.dumps(body).encode() if body is not None else None)
    rq = urllib.request.Request(url, data=data, method=method)
    rq.add_header("X-Contrib-Token", TOKEN)
    # 🚨 The server enforces staleness, not this client. --no-update-check can skip the local
    # prompt, so the version has to travel with every request or the rule is decorative.
    rq.add_header("X-Client-Version", str(CLIENT_VERSION))
    if blob is not None:
        rq.add_header("Content-Type", "application/octet-stream")
    elif data:
        rq.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(rq, timeout=timeout) as r:
        blob = r.read()
    return blob if raw else json.loads(blob)


def _fetch_checkpoint(job):
    """Download the unit's checkpoint and verify its digest. Returns an ABSOLUTE path.

    ⚠️ The hash proves the file arrived intact; it does NOT make it safe. Loading any SB3
    checkpoint runs pickle over its metadata, so running this worker means trusting the project
    not to serve a malicious one -- the same trust you extend to anything you pip install. That
    asymmetry is why the server does not accept checkpoints from contributors: it is not willing
    to extend that trust in the other direction. See docs/DISTRIBUTED.md.

    🔑 Absolute, because evaluation chdirs into repo/v2 and a relative path would silently
    resolve somewhere else afterwards.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    name = os.path.basename(job["checkpoint"])
    dest = os.path.abspath(os.path.join(CACHE_DIR, name))

    def digest(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    if os.path.isfile(dest) and digest(dest) == job["sha256"]:
        print(f"  cached  {name}")
        return dest

    print(f"  fetching {name} ...", end="", flush=True)
    blob = _api(job["url"], raw=True, timeout=600)
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(blob)
    got = digest(tmp)
    if got != job["sha256"]:
        os.remove(tmp)
        raise ValueError(f"checksum mismatch (got {got[:12]}, expected {job['sha256'][:12]})")
    os.replace(tmp, dest)
    print(f" {len(blob) / 1e6:.1f} MB, digest ok")

    # Keep the cache bounded; a long-running worker would otherwise fill a disk with ~14 MB files.
    zips = sorted((os.path.join(CACHE_DIR, f) for f in os.listdir(CACHE_DIR)
                   if f.endswith(".zip")), key=os.path.getmtime, reverse=True)
    for old in zips[CACHE_KEEP:]:
        try:
            os.remove(old)
        except OSError:
            pass
    return dest


def _spool(result):
    """Persist a finished result BEFORE trying to send it.

    🚨 A unit costs about an hour. Submitting straight from memory means a dropped connection
    throws that hour away, which is the fastest way to lose a volunteer. On disk it survives a
    crash, a reboot and a lost network, and the next loop sends it.
    """
    os.makedirs(SPOOL_DIR, exist_ok=True)
    p = os.path.join(SPOOL_DIR, f"{result['job_id']}.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f)
    os.replace(tmp, p)
    return p


def _flush_spool():
    """Send anything left over from earlier. Returns how many got through."""
    if not os.path.isdir(SPOOL_DIR):
        return 0
    sent = 0
    for fn in sorted(os.listdir(SPOOL_DIR)):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(SPOOL_DIR, fn)
        try:
            with open(p, encoding="utf-8") as f:
                result = json.load(f)
        except Exception:
            os.remove(p)            # unreadable: nothing to recover, do not retry forever
            continue
        try:
            r = _api("/api/contrib/eval/result", "POST", result)
            os.remove(p)
            sent += 1
            print(f"  submitted {result.get('checkpoint')} -- {r.get('note', 'ok')}")
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                # The server rejected the CONTENT. Retrying cannot help and would spool forever.
                print(f"  !! rejected permanently ({e.code}), discarding: {fn}")
                os.remove(p)
            else:
                print(f"  submit deferred ({e.code}); will retry")
                break
        except Exception as e:
            print(f"  submit deferred ({e}); will retry")
            break
    return sent


def _run_unit(job, ckpt):
    """Score one unit. Returns the metrics dict for the single run it performs.

    One unit is exactly one run, because the server records one metrics object per result and
    the median it eventually computes wants independent samples from different seeds -- which is
    what it hands out. Bundling runs here would average them before the server ever saw them.
    """
    import gamereg
    g = gamereg.get(job.get("game", GAME))
    sys.path.insert(0, os.path.abspath(g.v2))
    os.chdir(g.v2)                       # the env's own paths are relative to repo/v2
    import eval_checkpoint as ec
    ec.GAME = job.get("game", GAME)
    # budget_s=None => bounded by STEPS. With the seed, that is what makes the unit reproducible
    # and therefore comparable against another contributor's replica of it.
    entry = ec.evaluate(ckpt, 1, None, int(job["steps"]), ec.map_names(), seed=int(job["seed"]))
    runs = entry.get("per_run") or []
    if not runs:
        raise RuntimeError("evaluation produced no run")
    return runs[0]


def eval_loop(once=False, max_units=0):
    """Pull eval work from the box and score it, forever.

    🔑 PULL, NEVER PUSH -- nothing listens, so there is no port to forward and no inbound rule
    to get wrong. The box never initiates a connection to a contributor.
    """
    if not TOKEN:
        print("CONTRIB_TOKEN is not set. Get one with:\n"
              f"  curl -X POST {BOX}/api/contrib/register "
              "-H 'Content-Type: application/json' -d '{\"handle\":\"yourname\"}'\n"
              "It is shown once and only its hash is stored, so save it.")
        return 1
    import gamereg
    good, detail = gamereg.get(GAME).verify_rom()
    if not good:
        # 🚨 Hard stop. A wrong ROM produces entirely plausible numbers for a different game,
        # which would quietly poison the score table rather than failing visibly.
        print(f"refusing to start: {detail}")
        return 1

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    print(f"contributing eval to {BOX} (game {GAME}). Ctrl-C to stop after the current unit.\n")

    done = 0
    while not _STOP:
        _flush_spool()
        try:
            r = _api("/api/contrib/eval/next")
        except Exception as e:
            print(f"  no answer from the box ({e}); retrying in 60s")
            _nap(60)
            continue

        job = r.get("job")
        if not job:
            if once:
                print("  nothing needs scoring right now.")
                return 0
            print(f"  nothing to score; checking again in {IDLE_SLEEP // 60} min")
            _nap(IDLE_SLEEP)
            continue

        print(f"[{time.strftime('%H:%M:%S')}] {job['checkpoint']}  "
              f"seed={job['seed']} steps={int(job['steps']):,}")
        cwd = os.getcwd()
        try:
            ckpt = _fetch_checkpoint(job)
            t0 = time.time()
            metrics = _run_unit(job, ckpt)
        except Exception as e:
            print(f"  !! unit failed: {e}")
            os.chdir(cwd)
            _nap(30)
            continue
        finally:
            os.chdir(cwd)            # _run_unit chdirs; the loop must not inherit that

        result = {
            "job_id": job["job_id"],
            "checkpoint": job["checkpoint"],
            "seed": int(job["seed"]),
            "steps": int(job["steps"]),
            "metrics": {k: metrics[k] for k in
                        ("badges", "maps", "tiles", "events", "levels_sum",
                         "req_ever", "req_stage", "knows_cut") if k in metrics},
        }
        _spool(result)               # on disk BEFORE the network is involved
        m = result["metrics"]
        print(f"  done in {(time.time() - t0) / 60:.0f} min -- "
              f"badges={m.get('badges')} maps={m.get('maps')} "
              f"tiles={m.get('tiles')} stage={m.get('req_stage')}")
        _flush_spool()

        done += 1
        if once or (max_units and done >= max_units):
            break

    _flush_spool()
    print(f"\nstopped after {done} unit(s). Thank you.")
    return 0


def _nap(seconds):
    """Sleep, but wake up promptly when asked to stop."""
    end = time.time() + seconds
    while time.time() < end and not _STOP:
        time.sleep(min(1.0, end - time.time()))


# ---- ladder: donate save states ----------------------------------------------------------
# 🔑 THE HIGHEST-VALUE JOB, and the one a human can do better than the agent. Published work on
# this environment reports that no agent has ever obtained HM01, which hard-blocks the third
# gym. Training workers start from states on a "ladder" of increasing depth, so a state from
# somewhere the agent cannot reach on its own is worth more than any number of scored hours.
#
# 🔑 A SAVE STATE IS INERT BYTES -- no pickle, no code -- which is why the server accepts these
# from strangers when it will never accept a trained checkpoint. It verifies each one by loading
# it into a real emulator and reading the game's own flags, so there is nothing to forge: the
# depth it records is read out of the game, not taken from the uploader.


def _sidecar_stage(state_path):
    """The true stage of a harvested state, from the .json the harness wrote beside it.

    🚨 READ, NEVER RECOMPUTE. The in-game progress flag count is a POINT-IN-TIME popcount and the
    game CLEARS several required flags once their scene ends (Bill's, the S.S. Anne's). So a
    state saved just after HM01 -- the deepest and most valuable thing here -- can read as FEWER
    set flags than one saved before Bill, and anything that recomputes depth from the state files
    ranks the best states as the shallowest. The harness held the cumulative mask at save time
    and simply knew the answer; this reads that answer back.
    """
    try:
        with open(state_path + ".json", encoding="utf-8") as f:
            return int(json.load(f)["stage"])
    except Exception:
        return None                    # a human-supplied state has no sidecar; that is fine


def _upload_state(path, stage=None):
    """Send one save state. Returns True if the box accepted it.

    The server classifies it independently, so a stage we print here is a label, never a claim:
    the number that counts is the one it reads out of the emulator.
    """
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            blob = f.read()
    except OSError as e:
        print(f"  !! cannot read {name}: {e}")
        return False
    label = f"stage {stage}" if stage is not None else "stage unknown"
    print(f"  uploading {name} ({len(blob) / 1024:.0f} KB, {label}) ...", end="", flush=True)
    try:
        r = _api("/api/contrib/ladder", "POST", blob=blob, timeout=300)
    except urllib.error.HTTPError as e:
        # The box explains its refusals (too shallow, would not load, client too old) and those
        # explanations are the whole value of the response -- printing "HTTP 400" instead would
        # send a contributor to look for a bug in their own machine.
        try:
            detail = json.loads(e.read().decode("utf-8", "replace"))
            msg = detail.get("error") or detail
        except Exception:
            msg = f"HTTP {e.code}"
        print(f"\n  !! rejected: {msg}")
        return False
    except Exception as e:
        print(f"\n  !! could not send: {e}")
        return False
    print(f" accepted at stage {r.get('stage')}")
    return True


def _sent_dir():
    d = os.path.join(HARVEST_DIR, "sent")
    os.makedirs(d, exist_ok=True)
    return d


def _mark_sent(path):
    """Move an accepted state aside so a later pass cannot upload it again.

    Kept rather than deleted: it is the contributor's artifact too, and a state that turned out
    to be interesting is worth still having on disk.
    """
    try:
        os.replace(path, os.path.join(_sent_dir(), os.path.basename(path)))
        if os.path.isfile(path + ".json"):
            os.replace(path + ".json",
                       os.path.join(_sent_dir(), os.path.basename(path) + ".json"))
    except OSError as e:
        print(f"  (uploaded, but could not file it away: {e})")


def ladder_upload(paths):
    """Donate save states a human produced. The high-value path -- no emulation needed here."""
    if not TOKEN:
        print("CONTRIB_TOKEN is not set; see `worker.py --check`.")
        return 1
    sent = 0
    for p in paths:
        p = os.path.abspath(os.path.expanduser(p))
        if not os.path.isfile(p):
            print(f"  !! no such file: {p}")
            continue
        if _upload_state(p, _sidecar_stage(p)):
            sent += 1
    print(f"\n{sent} of {len(paths)} state(s) accepted.")
    # ⚠️ Non-zero when nothing landed, so an unattended caller can tell. A partial success is
    # still a success: the accepted ones are on the ladder.
    return 0 if sent else 1


def _harvest_new(before):
    """States written since `before` was taken, deepest first, with their true stages."""
    out = []
    try:
        names = os.listdir(HARVEST_DIR)
    except OSError:
        return out
    for n in sorted(names):
        if not n.endswith(".state") or n in before:
            continue
        p = os.path.join(HARVEST_DIR, n)
        if os.path.isfile(p):
            out.append((_sidecar_stage(p) or 0, p))
    # Deepest first: if the upload is interrupted, the rung that matters most is already gone.
    return sorted(out, reverse=True)


def ladder_run(once=False, max_units=0, steps=None):
    """Play the checkpoint that is currently ON AIR and donate whatever depths it reaches.

    🔑 NOT an eval job. eval/next hands out whatever most needs scoring, which is usually a
    mediocre candidate -- exactly the wrong thing to run when the goal is to get somewhere deep.
    The box's ladder endpoint hands out the best thing it has instead.
    """
    if not TOKEN:
        print("CONTRIB_TOKEN is not set; see `worker.py --check`.")
        return 1
    import gamereg
    g = gamereg.get(GAME)
    good, detail = g.verify_rom()
    if not good:
        print(f"refusing to start: {detail}")
        return 1

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    os.makedirs(HARVEST_DIR, exist_ok=True)
    print(f"contributing ladder states to {BOX} (game {GAME}). "
          f"Ctrl-C to stop after the current run.\n")

    done = 0
    while not _STOP:
        try:
            t = _api("/api/contrib/ladder/next")["target"]
        except Exception as e:
            print(f"  no answer from the box ({e}); retrying in 60s")
            _nap(60)
            continue

        want = t.get("want") or []
        print(f"[{time.strftime('%H:%M:%S')}] {t['checkpoint']}  "
              f"harvesting stage >= {t.get('min_stage')}")
        if want:
            print(f"  the ladder is missing stage(s): {', '.join(str(w) for w in want)}")

        cwd = os.getcwd()
        try:
            ckpt = _fetch_checkpoint(t)
            sys.path.insert(0, os.path.abspath(g.v2))
            os.chdir(g.v2)                   # the env's own paths are relative to repo/v2
            import eval_checkpoint as ec
            ec.GAME = GAME
            # 🚨 Point the harness at OUR directory before it runs, not after: harvest_state()
            # reads this module global each time it saves, mid-run.
            ec.HARVEST_DIR = os.path.abspath(HARVEST_DIR)
            # Harvest exactly what the box will accept. Below its threshold the upload is
            # refused, and an hour that ends in a rejection reads as a broken client.
            if t.get("min_stage") is not None:
                ec.HARVEST_MIN_STAGE = int(t["min_stage"])
            before = set(os.listdir(ec.HARVEST_DIR))
            t0 = time.time()
            # runs=1, no time budget, bounded by steps -- and harvest=True, which is the only
            # difference from an eval unit that matters: the emulator state is kept each time a
            # new depth is reached instead of being thrown away at the end of the run.
            ec.evaluate(ckpt, 1, None, int(steps or LADDER_STEPS), ec.map_names(), harvest=True)
        except Exception as e:
            print(f"  !! run failed: {e}")
            os.chdir(cwd)
            _nap(30)
            continue
        finally:
            os.chdir(cwd)                    # evaluate() chdirs; the loop must not inherit it

        found = _harvest_new(before)
        print(f"  run finished in {(time.time() - t0) / 60:.0f} min -- "
              f"{len(found)} state(s) worth donating")
        for stage, p in found:
            if _upload_state(p, stage or None):
                _mark_sent(p)

        done += 1
        if once or (max_units and done >= max_units):
            break

    print(f"\nstopped after {done} run(s). Thank you.")
    return 0


def _not_yet(job):
    print(f"'{job}' is not accepted from contributors -- see docs/DISTRIBUTED.md for why.")
    print("What you can run today:")
    print("  worker.py --check                    validate this machine")
    print("  worker.py eval --local <checkpoint>  score a checkpoint locally")
    print("  worker.py eval                       score checkpoints for the box")
    print("  worker.py ladder                     play the best checkpoint, donate deep states")
    print("  worker.py ladder --file <state>      donate a save state you produced")
    return 2


def main():
    ap = argparse.ArgumentParser(description="Donate compute to the Pokemon RL project.")
    ap.add_argument("job", nargs="?", default=None, choices=("eval", "ladder", "train"))
    ap.add_argument("--check", action="store_true", help="validate setup and exit")
    ap.add_argument("--local", metavar="CKPT",
                    help="score this local checkpoint instead of pulling work from the box")
    ap.add_argument("--seed", type=int, default=1,
                    help="a work unit is (checkpoint, seed, steps); the seed makes it reproducible")
    ap.add_argument("--file", metavar="STATE", action="append",
                    help="ladder: donate a save state you already have, instead of playing for "
                         "one. Repeatable. This is the most valuable thing you can send.")
    # Default None, not a number: the ladder job takes its length from LADDER_STEPS (which an
    # env var can raise) and an argparse default would silently override that.
    ap.add_argument("--steps", type=int, default=None, help="steps per run")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--once", action="store_true",
                    help="take a single work unit and exit (use this for your first run)")
    ap.add_argument("--max-units", type=int, default=0, metavar="N",
                    help="stop after N units (0 = keep going until interrupted)")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="accept a client update without asking (for unattended runs)")
    ap.add_argument("--no-update-check", action="store_true",
                    help="skip the version check. Your results will still be REJECTED if the "
                         "client is stale -- this exists for debugging, not for opting out.")
    a = ap.parse_args()

    if a.check or a.job is None:
        return check()
    # ⚠️ The gate is only on paths that SUBMIT. --check and `eval --local` compute nothing the
    # box will pool, and someone on a stale client needs those two working precisely so they can
    # diagnose their machine before updating anything.
    if a.job == "eval" and a.local:
        return eval_local(a.local, a.seed, a.steps or DEFAULT_UNIT_STEPS, a.runs)
    if not a.no_update_check and not enforce_version(assume_yes=a.yes):
        return 1
    if a.job == "eval":
        return eval_loop(once=a.once, max_units=a.max_units)
    if a.job == "ladder":
        # --file donates something that already exists and needs no emulator, which is why it is
        # checked first: it is the path a contributor takes after playing the game themselves.
        if a.file:
            return ladder_upload(a.file)
        return ladder_run(once=a.once, max_units=a.max_units, steps=a.steps)
    return _not_yet(a.job)


if __name__ == "__main__":
    raise SystemExit(main())
