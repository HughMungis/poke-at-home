#!/usr/bin/env python3
"""The contributor client. Runs inside the container; pulls work, never accepts a connection.

  python3 worker.py --check              # validate this machine before donating anything
  python3 worker.py eval --local <ckpt>  # score a checkpoint locally (works TODAY, no server)
  python3 worker.py eval                 # pull eval work from the box   [server not live yet]
  python3 worker.py ladder               # contribute save states        [server not live yet]
  python3 worker.py train                # PPO, upload candidates        [server not live yet]

🔑 PULL, NEVER PUSH. The contributor's machine asks the box for work over HTTPS. Nothing
listens on a public port, so there is no forwarding to set up and no inbound rule to get wrong.
The local control panel binds 127.0.0.1 only.

⚠️ STATUS: `--check` and `eval --local` are real and work. The three networked subcommands are
deliberately stubs that say so -- /api/contrib/* does not exist on the server yet. A stub that
announces itself is honest; one that silently no-ops wastes a contributor's evening. See
docs/DISTRIBUTED.md for what lands when.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # repo root: gamereg.py, eval_checkpoint.py live here
sys.path.insert(0, ROOT)

BOX = os.environ.get("CONTRIB_BOX", "https://franksriracha.zip")
TOKEN = os.environ.get("CONTRIB_TOKEN", "")
GAME = os.environ.get("CONTRIB_GAME", "red")

# One hour of wall clock measures ~570k steps on the server. A work unit is bounded by STEPS,
# not time, so that two machines of different speeds compute the same thing -- see check().
DEFAULT_UNIT_STEPS = 550_000


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
    a = ap.parse_args()

    if a.check or a.job is None:
        return check()
    if a.job == "eval" and a.local:
        return eval_local(a.local, a.seed, a.steps, a.runs)
    return _not_yet(a.job)


if __name__ == "__main__":
    raise SystemExit(main())
