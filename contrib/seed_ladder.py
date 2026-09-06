#!/usr/bin/env python3
"""Play Pokemon Red and bank save states for the demonstration ladder.

  python seed_ladder.py --rom PokemonRed.gb
  python seed_ladder.py --rom PokemonRed.gb --from init.state    # skip the opening
  python seed_ladder.py --rom PokemonRed.gb --upload             # send each one to the box

Play in the window. **Press Z whenever you reach a milestone** — this copies the state
somewhere permanent and tells you which stage you just banked. X reloads PyBoy's last save if
you need to retry something. Close the window when you are done.

🔑 WHY THIS IS WORTH AN EVENING. The ladder is what lets a training run START from a position
the agent almost never reaches on its own. Eval harvests such states automatically, but only
19% of runs get past stage 10 -- about one state a day. Playing to Misty, Bill, HM01 and Cut by
hand gives complete coverage of exactly those stages in one sitting, and every training run
afterwards can begin from them.

🚨 SAVE STATES ARE VERSION-LOCKED TO PYBOY. A state written by a newer PyBoy will not load on
the box and the whole evening is wasted -- silently, because the failure appears later during
import. This script checks the version FIRST and refuses to run on a mismatch.

🚨 A PyBoy state is NOT interchangeable with a BizHawk/VBA/mGBA save state. Those are different
formats entirely. You must play in this window. (An in-game .sav is portable, so if you would
rather play elsewhere: save in-game there, then run this with --sav to boot from it and bank a
PyBoy state at the same point.)
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The box runs this. States written by anything newer will not load there.
REQUIRED_PYBOY = os.environ.get("LADDER_PYBOY_VERSION", "2.5.4")
BOX = os.environ.get("CONTRIB_BOX", os.environ.get("TRAIN_BOX", "https://franksriracha.zip"))
TOKEN = os.environ.get("TRAIN_TOKEN", "")


def load_stages(explicit=None):
    """[(stage, addr, bit, name)] from required_events.json, wherever it happens to be.

    ⚠️ Searched rather than assumed. This script runs on a machine whose layout we do not
    control -- /pc installs it beside train_worker.py while required_events.json goes into the
    repo's v2/ dir, which is neither of the two obvious relative paths. Getting this wrong is
    not fatal (states still save) but it costs the live "you just banked stage 14" feedback,
    which is the whole reason to run this interactively.
    """
    cands = [explicit] if explicit else []
    cands += [os.path.join(ROOT, "repo", "v2", "required_events.json"),
              os.path.join(HERE, "required_events.json"),
              os.path.join(ROOT, "required_events.json")]
    for root, dirs, files in os.walk(ROOT):
        if "required_events.json" in files:
            cands.append(os.path.join(root, "required_events.json"))
        dirs[:] = [d for d in dirs if d not in
                   (".git", "__pycache__", "venv", ".venv", "node_modules")
                   and not d.startswith("train_")]
    for cand in cands:
        if cand and os.path.isfile(cand):
            with open(cand, encoding="utf-8") as f:
                d = json.load(f)
            rows = d if isinstance(d, list) else list(d.values())[0]
            out = []
            for r in rows:
                # "0xD747-0" -> address 0xD747, bit 0
                a, b = r["flag"].split("-")
                out.append((int(r["stage"]), int(a, 16), int(b), r["name"]))
            return out
    return []


def stage_of(pyboy, stages):
    """(deepest stage currently set, its name). Read straight from memory -- no env needed.

    ⚠️ This is a POINT-IN-TIME read and the game CLEARS several of these flags once their scene
    ends, so it can under-report a genuinely deep state. It is here to tell you roughly where
    you are while playing, not to file anything: make_ladder on the box does the real
    classification, and the harvester's own sidecar is what settles a disagreement.
    """
    hi, name = 0, ""
    for st, addr, bit, nm in stages:
        try:
            if (pyboy.memory[addr] >> bit) & 1:
                if st > hi:
                    hi, name = st, nm
        except Exception:
            pass
    return hi, name


def upload(path, name):
    if not TOKEN:
        return "no TRAIN_TOKEN set — not uploaded"
    try:
        with open(path, "rb") as f:
            blob = f.read()
        rq = urllib.request.Request(BOX.rstrip("/") + "/api/train/ladder",
                                    data=blob, method="POST")
        rq.add_header("X-Train-Token", TOKEN)
        rq.add_header("X-Train-Game", os.environ.get("TRAIN_GAME", "red"))
        rq.add_header("X-Train-Name", name)
        rq.add_header("Content-Type", "application/octet-stream")
        with urllib.request.urlopen(rq, timeout=120) as r:
            json.loads(r.read())
        return "uploaded"
    except Exception as e:
        return f"upload failed ({e}) — the local copy is still good"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", default=os.path.join(ROOT, "repo", "PokemonRed.gb"))
    ap.add_argument("--from", dest="start", default=None,
                    help="a .state to begin from (e.g. init.state, or your last seed)")
    ap.add_argument("--sav", default=None,
                    help="an in-game .sav to boot from, if you played in another emulator")
    ap.add_argument("--out", default=os.path.join(ROOT, "ladder-seed"))
    ap.add_argument("--upload", action="store_true", help="send each state to the box as you go")
    ap.add_argument("--events", default=None, help="path to required_events.json, if not found")
    a = ap.parse_args()

    try:
        import importlib.metadata as md
        have = md.version("pyboy")
    except Exception:
        have = "unknown"
    print(f"PyBoy {have} (the box runs {REQUIRED_PYBOY})")
    if have != REQUIRED_PYBOY:
        # 🚨 Refuse rather than warn. A warning here costs an evening: every state written would
        # be rejected at import with "Cannot load state from a newer version of PyBoy", long
        # after the emulator is closed and the moment is gone.
        print(f"\n  STOP. Save states are version-locked, so states written by {have} will not\n"
              f"  load on the box. Install the matching version first:\n\n"
              f"      pip install pyboy=={REQUIRED_PYBOY}\n\n"
              f"  (Override with LADDER_PYBOY_VERSION only if you have changed the box too.)")
        return 1

    if not os.path.isfile(a.rom):
        print(f"no ROM at {a.rom} — pass --rom")
        return 1

    from pyboy import PyBoy
    os.makedirs(a.out, exist_ok=True)
    stages = load_stages(a.events)
    if not stages:
        print("  (no required_events.json found — states will still be saved, just unlabelled)")

    pyboy = PyBoy(a.rom, window="SDL2", sound_emulated=True)
    if a.sav:
        # An in-game save IS portable between emulators, unlike a save state.
        shutil.copy2(a.sav, os.path.splitext(a.rom)[0] + ".sav")
        print(f"  booting with your .sav — load your game from the title screen")
    if a.start and os.path.isfile(a.start):
        with open(a.start, "rb") as f:
            pyboy.load_state(f)
        print(f"  started from {a.start}")

    # PyBoy's own Z hotkey writes ONE fixed file, <rom>.state, and overwrites it every time.
    # Watching its mtime turns that into "the user asked for a snapshot" without this script
    # needing to read the keyboard at all -- which is what makes it work identically on Windows,
    # macOS and Linux.
    hot = a.rom + ".state"
    last = os.path.getmtime(hot) if os.path.exists(hot) else 0
    n, banked = 0, []
    print("\n  PLAY. Press Z at each milestone to bank a state. X reloads. Close the window "
          "when done.\n")
    try:
        while pyboy.tick():
            if not os.path.exists(hot):
                continue
            m = os.path.getmtime(hot)
            if m <= last:
                continue
            last = m
            time.sleep(0.15)          # let PyBoy finish writing before copying
            st, nm = stage_of(pyboy, stages)
            n += 1
            name = f"seed_{st:02d}_{n:03d}.state"
            dest = os.path.join(a.out, name)
            shutil.copy2(hot, dest)
            note = upload(dest, name) if a.upload else "saved locally"
            print(f"  🪜 banked stage {st:2} — {nm or 'unlabelled'}  [{name}] {note}")
            banked.append((st, name))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            pyboy.stop(save=False)
        except Exception:
            pass

    print(f"\n  {len(banked)} state(s) in {a.out}")
    if banked:
        deep = sorted({s for s, _ in banked})
        print(f"  stages covered: {', '.join(map(str, deep))}")
    if banked and not a.upload:
        print("\n  Install them on the box with:\n"
              f"      python3 make_ladder.py --from-dir {a.out} --max-per-stage 8\n"
              "  (or re-run this with --upload and TRAIN_TOKEN set to send them as you play)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
