#!/usr/bin/env python3
"""The contributor client. Runs inside the container; pulls work, never accepts a connection.

  python3 worker.py --check              # validate this machine before donating anything
  python3 worker.py eval --local <ckpt>  # score a checkpoint you already have, no server
  python3 worker.py eval --once          # take ONE unit from the box and stop
  python3 worker.py eval                 # keep taking eval work until interrupted
  python3 worker.py ladder               # play episodes, contribute deep save states
  python3 worker.py train                # PPO, upload candidates        [not accepted -- see below]

🔑 PULL, NEVER PUSH. The contributor's machine asks the box for work over HTTPS. Nothing
listens on a public port, so there is no forwarding to set up and no inbound rule to get wrong.

⚠️ STATUS: `--check`, `eval --local`, `eval` and `ladder` are all real. `train` is deliberately
NOT accepted from contributors and may never be: loading a
checkpoint runs pickle over its metadata, which is arbitrary code execution, so the server
takes numbers and save states -- things it can verify -- and not executable code. A stub that
announces itself is honest; one that silently no-ops wastes a contributor's evening.
See docs/DISTRIBUTED.md.
"""
import argparse
import glob
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


def _api(path, method="GET", body=None, timeout=120, raw=False):
    """One call to the box, carrying the contributor token. Returns parsed JSON, or bytes if raw.

    Raises on transport failure so the caller can decide whether to retry; the loop treats a
    network error as "wait and try again", never as "this unit failed".
    """
    url = BOX.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    rq = urllib.request.Request(url, data=data, method=method)
    rq.add_header("X-Contrib-Token", TOKEN)
    if data:
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
            # 🚨 ONLY a rejection of the CONTENT is permanent. This used to discard on any 4xx
            # except 429, which threw away an hour of completed work whenever the problem was
            # the REQUEST rather than the result: a 403 from a mistyped or newly-rotated token
            # deleted every queued result as it was submitted, and 401/408 did the same.
            # Verified by reproduction before changing. 400 (bad shape) and 413 (too large) are
            # genuinely hopeless — the same bytes will always be refused.
            if e.code in (400, 413, 422):
                print(f"  !! rejected permanently ({e.code}), discarding: {fn}")
                os.remove(p)
            else:
                print(f"  submit deferred ({e.code}); will retry")
                break
        except Exception as e:
            print(f"  submit deferred ({e}); will retry")
            break
    return sent


def _run_unit(job, ckpt, on_step=None):
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
    entry = ec.evaluate(ckpt, 1, None, int(job["steps"]), ec.map_names(),
                        seed=int(job["seed"]), on_step=on_step)
    runs = entry.get("per_run") or []
    if not runs:
        raise RuntimeError("evaluation produced no run")
    return runs[0]


def _panel_hook(panel, job, run_no, runs):
    """An on_step callback that feeds the local panel. Returns None if there is no panel."""
    if panel is None:
        return None
    st = panel.STATE
    st.update({"checkpoint": job.get("checkpoint"), "seed": job.get("seed"),
               "run": run_no, "runs": runs, "note": ""})

    def hook(env, steps):
        st["steps"] = steps
        # Cheap reads only — this runs on every step. The screen encode throttles itself.
        try:
            seen = getattr(env, "seen_coords", {}) or {}
            st["tiles"] = len(seen)
            st["maps"] = len({k.rsplit("m:", 1)[-1] for k in seen})
            st["badges"] = int(env.get_badges())
            st["stage"] = int(getattr(env, "max_required_rew", 0) +
                              getattr(env, "swarm_loaded_stage", 0))
        except Exception:
            pass
        panel.publish_frame(env)
    return hook


def _start_panel(job_name, handle=None):
    """Best-effort. A panel that cannot start must never stop the work."""
    try:
        import panel as _p
    except Exception:
        return None
    url = _p.start()
    _p.STATE.update({"job": job_name, "handle": handle,
                     "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "note": "waiting for work"})
    if url:
        print(f"  📺 watch it work: {url}")
    else:
        print(f"  (panel port {_p.PORT} busy — carrying on without it)")
    return _p


def _panel_wait_if_paused(panel):
    """Honour the panel's pause button BETWEEN units, never mid-unit.

    ⚠️ Pausing mid-unit would abandon partial work and report nothing, which is worse than
    finishing the hour. The button says "pause after this run" for that reason.
    """
    if panel is None:
        return
    while panel.STATE.get("paused") and not _STOP:
        panel.STATE["note"] = "paused — click resume when you want it to carry on"
        time.sleep(2)
    if panel is not None:
        panel.STATE["note"] = ""


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
    print(f"contributing eval to {BOX} (game {GAME}). Ctrl-C to stop after the current unit.")
    panel = _start_panel("eval")
    print()

    done = 0
    while not _STOP:
        _panel_wait_if_paused(panel)
        if _STOP:
            break
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
            metrics = _run_unit(job, ckpt, on_step=_panel_hook(panel, job, 1, 1))
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
        if panel is not None:
            panel.STATE["results_sent"] = panel.STATE.get("results_sent", 0) + 1
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


def ladder_loop(once=False, minutes=60.0):
    """Play episodes with the current policy and contribute any DEEP save states they reach.

    🔑 THIS IS THE HIGHEST-VALUE JOB AND IT IS FULLY AUTOMATIC. Every model this project has
    produced plateaus at required-event stage 14, and published work on this environment reports
    no agent ever obtaining HM01 (stage 15). A "ladder" of save states lets training START from
    depths the agent almost never reaches unaided, which is the mechanism that got a different
    project past its own walls. The box harvests roughly one usable state per eval pass; many
    machines doing it in parallel is the whole point.

    You do not play the game. The worker runs the same evaluation episodes as the `eval` job with
    harvesting switched on, and uploads whatever deep states fall out.

    🚨 A contributed state is ~167 KB of INERT BYTES -- no pickle, no executable content -- which
    is exactly why this job can be open to strangers when contributed CHECKPOINTS never will be.
    The server verifies each one by loading it into a real emulator and reading the game's own
    flags, so a fabricated file cannot claim a depth it does not have.
    """
    if not TOKEN:
        print("CONTRIB_TOKEN is not set. Register first — see --check.")
        return 1
    import gamereg
    good, detail = gamereg.get(GAME).verify_rom()
    if not good:
        print(f"refusing to start: {detail}")
        return 1

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)
    g = gamereg.get(GAME)
    harvest_dir = os.path.join(ROOT, "ladder-harvest")
    print(f"contributing ladder states to {BOX}. Ctrl-C to stop after the current episode.")
    panel = _start_panel("ladder")
    print()

    sent = 0
    while not _STOP:
        _panel_wait_if_paused(panel)
        if _STOP:
            break
        try:
            r = _api("/api/contrib/eval/next")
            job = r.get("job")
        except Exception as e:
            print(f"  no answer from the box ({e}); retrying in 60s")
            _nap(60)
            continue
        if not job:
            print("  nothing to run right now; waiting")
            _nap(IDLE_SLEEP)
            continue

        cwd = os.getcwd()
        try:
            ckpt = _fetch_checkpoint(job)
            sys.path.insert(0, os.path.abspath(g.v2))
            os.chdir(g.v2)
            import eval_checkpoint as ec
            ec.GAME = GAME
            # harvest=True writes a state each time a run reaches a NEW deep stage.
            ec.evaluate(ckpt, 1, minutes * 60.0, None, ec.map_names(),
                        seed=int(job["seed"]), harvest=True,
                        on_step=_panel_hook(panel, job, 1, 1))
        except Exception as e:
            print(f"  !! episode failed: {e}")
            os.chdir(cwd)
            _nap(30)
            continue
        finally:
            os.chdir(cwd)

        states = sorted(glob.glob(os.path.join(harvest_dir, "*.state")))
        if not states:
            print("  no deep states this episode (most runs do not reach one)")
        for sp in states:
            try:
                with open(sp, "rb") as f:
                    blob = f.read()
                rq = urllib.request.Request(BOX.rstrip("/") + "/api/contrib/ladder",
                                            data=blob, method="POST")
                rq.add_header("X-Contrib-Token", TOKEN)
                rq.add_header("Content-Type", "application/octet-stream")
                with urllib.request.urlopen(rq, timeout=180) as resp:
                    out = json.loads(resp.read())
                print(f"  🪜 accepted stage {out.get('stage')} — {out.get('note','')}")
                sent += 1
                if panel is not None:
                    panel.STATE["states_sent"] = panel.STATE.get("states_sent", 0) + 1
                os.unlink(sp)
                # the sidecar the harvester writes alongside; harmless if absent
                for extra in (sp + ".json",):
                    if os.path.exists(extra):
                        os.unlink(extra)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:200]
                print(f"  rejected ({e.code}): {body}")
                # A rejected state is not worth re-offering: the verdict came from loading it.
                os.unlink(sp)
            except Exception as e:
                print(f"  upload deferred ({e}); keeping it for next time")
                break
        if once:
            break
    print(f"\nstopped after contributing {sent} state(s). Thank you.")
    return 0


def _not_yet(job):
    print(f"'{job}' needs the /api/contrib/* endpoints, which are not live yet.")
    print("What exists today:")
    print("  worker.py --check                    validate this machine")
    print("  worker.py eval --local <checkpoint>  score a checkpoint locally")
    print("\nDesign and status: docs/DISTRIBUTED.md")
    return 2


def main():
    ap = argparse.ArgumentParser(description="Donate compute to the Pokemon RL project.")
    ap.add_argument("job", nargs="?", default=None, choices=("eval", "ladder", "train"))
    ap.add_argument("--check", action="store_true", help="validate setup and exit")
    ap.add_argument("--local", metavar="CKPT",
                    help="score this local checkpoint instead of pulling work from the box")
    ap.add_argument("--seed", type=int, default=1,
                    help="a work unit is (checkpoint, seed, steps); the seed makes it reproducible")
    ap.add_argument("--steps", type=int, default=DEFAULT_UNIT_STEPS, help="steps per run")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--once", action="store_true",
                    help="take a single work unit and exit (use this for your first run)")
    ap.add_argument("--max-units", type=int, default=0, metavar="N",
                    help="stop after N units (0 = keep going until interrupted)")
    a = ap.parse_args()

    if a.check or a.job is None:
        return check()
    if a.job == "eval" and a.local:
        return eval_local(a.local, a.seed, a.steps, a.runs)
    if a.job == "eval":
        return eval_loop(once=a.once, max_units=a.max_units)
    if a.job == "ladder":
        return ladder_loop(once=a.once)
    return _not_yet(a.job)


if __name__ == "__main__":
    raise SystemExit(main())
