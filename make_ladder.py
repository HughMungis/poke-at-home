#!/usr/bin/env python3
"""Turn a set of save states into a demonstration ladder the swarm can train from.

THE PROBLEM THIS SOLVES. Published results on this environment top out below gym 3 (no agent
obtained HM01) because the mid-game gates are an EXPLORATION problem, not a capability one.
⚠️ Our own runs HAVE reached HM01 six times and taught Cut three times -- but that is the best of
68 stochastic runs, and the median still stops around Brock. Rare success is exactly what a
ladder is for: it turns a lucky run into a starting position every later run can use.

The repo's own `init.state` already skips one such gate (it starts after Oak's Parcel, because
the backtracking was too much to find by chance). This does the same thing at every later gate
at once.

WHY A LADDER AND NOT A NEW START STATE. Moving `init.state` forward would mean the broadcast
opens in the middle of the game, which is worse television and teaches the agent nothing about
the early game. Instead the states go into the SWARM directory: `init.state` is untouched, the
broadcast still opens in Pallet Town, and training workers start from varying depths so every
segment gets practised. The policy that comes out plays the whole game from the beginning.

WHY STATES AND NOT THE DEMONSTRATOR'S BUTTON PRESSES. Behavioural cloning would need the
demonstrator's ACTIONS in our action space, and ours is one decision per 24 frames while a TAS
presses buttons on exact frames -- inside one window a run may press A on frame 3 and Down on
frame 11, and we could record only one. The precision is the whole point of a TAS, so cloning
it through that filter throws away what made it work. Positions survive the filter intact.

  python3 make_ladder.py --from-dir ~/tas_states           # classify and install
  python3 make_ladder.py --from-dir ~/tas_states --dry     # show what would happen
  python3 make_ladder.py --report                          # coverage of the 17 stages
  python3 make_ladder.py --verify                          # every installed state still loads

🚨 PyBoy save states are VERSION-LOCKED. A state written by a newer PyBoy fails to load with
"Cannot load state from a newer version of PyBoy". Generate the ladder with the same version
the trainer and the broadcast use -- this script prints it and refuses states it cannot read.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamereg  # noqa: E402

# ⚠️ Through gamereg, not a literal. This path is now spelled in four places (here, train_worker's
# --swarm, run_weekend.ps1's summary, /api/train/ladder) and when they were independent they
# disagreed -- states were written where nothing read them. gamereg.ladder_dir is the definition.
DEFAULT_SWARM = gamereg.ladder_dir(gamereg.DEFAULT_SLUG)


def stage_names(v2):
    try:
        with open(os.path.join(v2, "required_events.json"), encoding="utf-8") as f:
            d = json.load(f)
        rows = d if isinstance(d, list) else list(d.values())[0]
        # Entries are {"stage": n, "flag": "0xD747-0", "name": "Followed Oak Into Lab"} --
        # take the name, not the whole dict, or the report prints raw JSON as the milestone.
        return [r.get("name", str(r)) if isinstance(r, dict) else str(r) for r in rows]
    except Exception:
        return []


def open_env(game):
    """One env, reused for every state. Its own reset() loads init.state, but we only ever call
    load_state + the reader methods, so nothing here depends on where it started."""
    g = gamereg.get(game)
    sys.path.insert(0, g.v2)
    os.chdir(g.v2)
    sys.path.insert(0, HERE)
    import eval_checkpoint as ev
    env = ev.make_env(req_obs=False)
    env.reset()
    return env


def classify(env, path):
    """(required_stage, badges, coords) for one save state, or None if it will not load.

    Reuses the env's OWN readers rather than re-deriving the addresses. A second copy of the
    bit table would be one more thing to drift out of step with red_gym_env_v2.py.
    """
    try:
        with open(path, "rb") as f:
            env.pyboy.load_state(f)
    except Exception as e:
        return None, str(e)
    try:
        # 🚨 THE DEEPEST SET FLAG, NOT THE COUNT OF THEM. This used to return
        # get_required_events_reward(), which is a POPCOUNT -- correct as a reward, wrong as a
        # stage, and the two diverge the moment the game skips a milestone. Demonstrated on the
        # broadcast's own save: flags 1,2,3,4,5,7 set (stage 6 "Got Pokeballs From Oak" never
        # happened), so the count said 6 and the state was filed and LABELLED as stage 6 when it
        # was really at stage 7. Every ladder file would have carried the wrong number, and
        # _swarm_adopt orders by exactly that number.
        bits = env.read_required_event_bits()
        stage = max((i + 1 for i, b in enumerate(bits) if b), default=0)
        return (stage, int(env.get_badges()), env.get_game_coords()), None
    except Exception as e:
        return None, str(e)


def digest(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def installed(swarm):
    """{sha1: filename} of what is already in the ladder, so re-running is idempotent."""
    out = {}
    if not os.path.isdir(swarm):
        return out
    for n in os.listdir(swarm):
        if n.startswith("stage_") and n.endswith(".state"):
            out[digest(os.path.join(swarm, n))] = n
    return out


def ladder_stages(swarm):
    """{stage: [filenames]} currently installed."""
    out = {}
    if not os.path.isdir(swarm):
        return out
    for n in sorted(os.listdir(swarm)):
        if n.startswith("stage_") and n.endswith(".state"):
            try:
                out.setdefault(int(n[:-6].split("_")[1]), []).append(n)
            except (IndexError, ValueError):
                continue
    return out


def cmd_report(swarm, names):
    have = ladder_stages(swarm)
    print(f"ladder: {swarm}")
    total = sum(len(v) for v in have.values())
    print(f"  {total} state(s) across {len(have)} distinct stage(s)\n")
    print("  %-4s %-34s %s" % ("st", "milestone", "states"))
    for i, nm in enumerate(names, 1):
        n = len(have.get(i, []))
        bar = ("#" * min(n, 12)) if n else "-- none --"
        print("  %-4d %-34s %s" % (i, str(nm)[:34], bar))
    missing = [i for i in range(1, len(names) + 1) if not have.get(i)]
    if missing:
        # Not fatal: adoption samples whatever exists. But a gap is a segment nothing ever
        # practises from, which is exactly what the ladder is for.
        print(f"\n  ⚠ no states for stage(s): {', '.join(map(str, missing))}")
    if 0 in have:
        print(f"  note: {len(have[0])} state(s) at stage 0 (before the first milestone)")
    return 0


def cmd_verify(env, swarm):
    bad = 0
    for n in sorted(os.listdir(swarm)) if os.path.isdir(swarm) else []:
        if not (n.startswith("stage_") and n.endswith(".state")):
            continue
        res, err = classify(env, os.path.join(swarm, n))
        if res is None:
            print(f"  BAD  {n}: {err[:70]}")
            bad += 1
        else:
            st, bd, xy = res
            print(f"  ok   {n:<28} stage={st:<3} badges={bd} at {xy}")
    print(f"\n  {bad} unreadable state(s)")
    return 1 if bad else 0


def cmd_import(env, swarm, src, dry, names, max_per_stage=0):
    """Classify every state in `src` and install the ones that are new.

    ⚠️ `max_per_stage` matters once states arrive automatically rather than by hand. _swarm_adopt
    picks uniformly at random among whatever is installed, so an unbounded import from a
    continuously-running eval would fill the ladder with hundreds of copies of the easy stage the
    agent reaches every run, and a worker asking for a start position would almost always get
    that one. A cap keeps the ladder's SHAPE useful rather than just its size.
    """
    if not os.path.isdir(src):
        raise SystemExit(f"not a directory: {src}")
    files = sorted(os.path.join(src, n) for n in os.listdir(src)
                   if n.lower().endswith(".state"))
    if not files:
        raise SystemExit(f"no .state files in {src}")
    os.makedirs(swarm, exist_ok=True)
    seen = installed(swarm)
    have = ladder_stages(swarm)
    added, dupe, bad = 0, 0, 0
    print(f"{len(files)} candidate state(s) from {src}\n")
    for p in files:
        d = digest(p)
        if d in seen:
            print(f"  dup  {os.path.basename(p):<34} already installed as {seen[d]}")
            dupe += 1
            continue
        res, err = classify(env, p)
        if res is None:
            # Almost always a PyBoy version mismatch. Say so rather than "failed".
            print(f"  BAD  {os.path.basename(p):<34} {err[:60]}")
            bad += 1
            continue
        st, bd, xy = res
        # 🚨 classify() can only UNDER-report. It counts currently-set required flags, and the
        # game clears several of them once their scene ends, so a state saved after HM01 can
        # read as fewer flags than one saved before Bill. A harvester that watched the run
        # cumulatively knows better and leaves the number in a sidecar; take the higher of the
        # two. Hand-supplied states (a TAS dump) have no sidecar and rely on classify alone,
        # which is the conservative direction and therefore safe.
        # Both spellings: the harvester writes "<name>.state.json"; "<name>.json" is the other
        # obvious convention and costs nothing to accept.
        claimed = 0
        for side in (p + ".json", (p[:-6] + ".json") if p.endswith(".state") else None):
            if not side or not os.path.exists(side):
                continue
            try:
                with open(side, encoding="utf-8") as fh:
                    claimed = max(claimed, int(json.load(fh).get("stage", 0)))
            except Exception:
                pass
        try:
            if claimed > st:
                print(f"       (sidecar says stage {claimed}, classify read {st} -- "
                      f"cleared flags; using {claimed})")
                st = claimed
        except Exception:
            pass
        if max_per_stage and len(have.get(st, [])) >= max_per_stage:
            print(f"  full {os.path.basename(p):<34} stage {st:<3} already has "
                  f"{max_per_stage}; skipping")
            dupe += 1
            continue
        seq = len(have.get(st, [])) + 1
        name = f"stage_{st}_{seq:03d}.state"
        label = str(names[st - 1])[:26] if 1 <= st <= len(names) else "(before stage 1)"
        print(f"  +    {os.path.basename(p):<34} stage {st:<3} badges {bd}  {label}")
        if not dry:
            shutil.copy2(p, os.path.join(swarm, name))
        # Recorded even on a dry run: two identical files INSIDE the source folder must be
        # reported as a duplicate, not counted twice. Only the copy is conditional.
        seen[d] = name
        have.setdefault(st, []).append(name)
        added += 1
    print(f"\n  {'would add' if dry else 'added'} {added}, duplicates {dupe}, unreadable {bad}")
    if bad:
        print("  ⚠ unreadable states are almost always a PyBoy version mismatch -- "
              "regenerate them with the version printed above.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-dir", help="directory of .state files to classify and install")
    ap.add_argument("--swarm", default=DEFAULT_SWARM)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--game", default="red")
    ap.add_argument("--max-per-stage", type=int, default=0, metavar="N",
                    help="stop installing a stage once it has N states (0 = no cap). Adoption "
                         "samples uniformly, so an uncapped automatic import buries the rare "
                         "deep states under hundreds of copies of the easy ones.")
    a = ap.parse_args()

    names = stage_names(gamereg.get(a.game).v2)
    # 🚨 BOTH paths must be made absolute HERE, before open_env() chdirs into the game's v2 dir.
    # `swarm` always was; `--from-dir` was resolved further down, i.e. AFTER the chdir, so a
    # relative path silently pointed at repo/v2/<name> and the tool reported "not a directory"
    # for a directory that plainly existed. Exactly the trap that made train_worker write the
    # swarm ladder somewhere training never read it.
    swarm = os.path.abspath(a.swarm)
    from_dir = os.path.abspath(a.from_dir) if a.from_dir else None

    if a.report and not (a.from_dir or a.verify):
        return cmd_report(swarm, names)

    try:
        import importlib.metadata as md
        print(f"PyBoy {md.version('pyboy')}  (states must be written by this version)\n")
    except Exception:
        pass
    env = open_env(a.game)
    try:
        if a.verify:
            return cmd_verify(env, swarm)
        if from_dir:
            rc = cmd_import(env, swarm, from_dir, a.dry, names, a.max_per_stage)
            print()
            cmd_report(swarm, names)
            return rc
        return cmd_report(swarm, names)
    finally:
        env.close()


if __name__ == "__main__":
    raise SystemExit(main())
