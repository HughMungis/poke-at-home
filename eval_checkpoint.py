#!/usr/bin/env python3
"""Phase A — score a policy checkpoint objectively, so "promote a new checkpoint" is a
decision with a criterion instead of a guess.

  python3 eval_checkpoint.py --all                  # every runs/*.zip, default budget
  python3 eval_checkpoint.py --checkpoint runs/poke_26214400.zip --runs 3 --minutes 60
  python3 eval_checkpoint.py --all --minutes 5 --runs 1     # quick smoke test
  python3 eval_checkpoint.py --report               # just print the stored results table

Design decisions that matter for the numbers being COMPARABLE:

🚨 Every run starts from init.state — never from run_state.state. The nightly broadcast
   resumes its saved run, but an evaluation must not: two checkpoints judged from different
   starting states aren't being compared, they're being handed different games. This also
   means eval NEVER touches the broadcast's save files (it opens its own env and never calls
   save_progress), so running it can't disturb or corrupt the live run.

🚨 deterministic=False, matching how nightly.py actually calls the policy. Evaluating with
   deterministic=True would measure a policy the stream never runs.

🚨 Multiple independent runs, reported as median + best. A single run of a stochastic policy
   in a game this long is extremely noisy — the difference between "reached Cerulean" and
   "looped in Pallet Town" can be one early coin flip. Median is the honest headline; best
   shows the ceiling.

⚠️ Refuses to start while the overnight broadcast is live. This box has 2 shared cores and
   the broadcast is a realtime encode — an uncapped eval alongside it would drop frames on
   air. Override with --force only if you know the broadcast is down.
"""
import argparse, json, os, sys, tempfile, time, uuid, warnings, collections

warnings.filterwarnings("ignore")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import gamereg

RANDOM_NAME = "(random)"        # pseudo-checkpoint: the untrained floor

HERE = os.path.dirname(os.path.abspath(__file__))
# 🚨 Per-game, resolved through gamereg. The eval is the ONE component that must handle every
# game AND every observation shape at once — it is where old and new checkpoints get compared —
# so nothing here may assume a single ROM, runs/ dir or results file. Rebound in main() from
# --game; the module-level values keep `--report` and direct imports working.
GAME = gamereg.DEFAULT_SLUG
V2 = gamereg.get(GAME).v2
RESULTS = gamereg.results_file(GAME)


def broadcast_live():
    """True if the nightly broadcast is on air (systemd unit active)."""
    import subprocess
    try:
        r = subprocess.run(["systemctl", "is-active", "sriracha-pokemon"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active"
    except Exception:
        return False          # can't tell -> don't block; the caller gates too


def map_names():
    try:
        with open(os.path.join(V2, "map_data.json"), encoding="utf-8") as f:
            return {str(r["id"]): r["name"] for r in json.load(f)["regions"]}
    except Exception:
        return {}


def needs_required_obs(ckpt):
    """Does this checkpoint expect the `required_events` observation key?

    🚨 The eval has to serve BOTH shapes at once and nothing else does. The broadcast only ever
    loads old checkpoints (gate off) and training only ever makes new ones (gate on) — but the
    eval compares them against each other, so it must build the env to match whichever file it
    is scoring. Read from the zip's stored space rather than try/except around PPO.load, so the
    decision is made from fact instead of from a caught error.
    """
    try:
        from stable_baselines3.common.save_util import load_from_zip_file
        data, _, _ = load_from_zip_file(ckpt, device="cpu", load_data=True)
        return "required_events" in data["observation_space"].spaces
    except Exception:
        return False          # oldest shape is the safe guess


def make_env(req_obs=False):
    """A FRESH env at init.state. session_path goes to the SYSTEM temp dir so nothing this
    writes can land next to the broadcast's real save files — and so it resolves on Windows,
    where a literal '/tmp' does not exist."""
    import importlib, pathlib
    g = gamereg.get(GAME)
    # Imported by NAME from the game spec rather than a literal, so a second game brings its own
    # env module without this file learning about it. Works because main() already put the
    # game's v2/ dir on sys.path and chdir'd into it.
    RedGymEnv = getattr(importlib.import_module(g.env_module), g.env_class)
    cfg = {'headless': True, 'save_final_state': False, 'early_stop': False,
           'action_freq': 24, 'init_state': '../' + gamereg.get(GAME).init_state,
           'max_steps': 2 ** 23,
           'print_rewards': False, 'save_video': False, 'fast_video': True,
           # 🚨 NOT a hardcoded '/tmp/poke_eval'. On Windows that resolves to '\\tmp\\poke_eval',
           # a directory that does not exist on the system drive, and every run died with
           # "[WinError 3] The system cannot find the path specified" before a single step.
           # This file runs on contributors' machines now, not only on the box.
           'session_path': pathlib.Path(tempfile.gettempdir()) / "poke_eval",
           'gb_path': '../' + gamereg.get(GAME).rom, 'debug': False,
           'sim_frame_dist': 2_000_000.0, 'extra_buttons': False,
           'required_events_obs': req_obs}
    return RedGymEnv(cfg)


def snapshot_metrics(env, names, ever=None):
    """Everything worth comparing between checkpoints, read straight off the env.

    🔑 `req*` IS THE METRIC THE INTERACTION-REWARD EXPERIMENT IS JUDGED ON, and it was missing
    until 2026-09-01: `events` here is get_all_events_reward(), the GENERIC popcount over ~2,558
    flags where "opened a menu" scores what "Beat Brock" scores. That is precisely the quantity
    the required_event reward exists to stop treating as progress, so scoring on it could not
    have answered whether the change worked. Every score recorded before that date has no
    req fields; that is expected, not corruption.

    ⚠️ Eval always resets to init.state, where base_required_flags is 0 (verified), so the raw
    count IS absolute progress along the chain. That is NOT true of a resumed mid-game save,
    where the env baselines it — do not copy this reasoning into the broadcast.
    """
    seen = getattr(env, "seen_coords", {}) or {}
    maps = collections.Counter(k.rsplit("m:", 1)[-1] for k in seen)
    try:
        events = float(env.get_all_events_reward())
    except Exception:
        events = 0.0
    out = {
        "badges": int(env.get_badges()),
        "events": events,
        "levels_sum": int(env.get_levels_sum()),
        "tiles": len(seen),
        "maps": len(maps),
        "map_names": sorted({names.get(m, f"map {m}") for m in maps}),
    }
    try:
        req_names = list(getattr(env, "required_event_names", []))
        # `req` is a point-in-time read and can go DOWN: several of these flags are cleared by
        # the game once their scene ends (Bill's, the S.S. Anne's). `req_max` is the env's own
        # ratchet and `req_stage` comes from the cumulative mask, so neither can regress.
        out["req"] = int(env.get_required_events_reward())
        out["req_max"] = int(getattr(env, "max_required_rew", 0))
        # 🔑 THE ACTUAL GATE, and it is not "Got Hm01". Holding the item does nothing — the
        # cuttable tree blocking gym 3 opens only once CUT is TAUGHT to a party member. A run
        # can therefore reach stage 15 and still be hard-blocked, which is a different state
        # from being stuck before Bill and deserves its own column.
        out["knows_cut"] = int(bool(env.knows_cut()))
        out["cut_max"] = int(getattr(env, "max_cut_rew", 0))
        if ever is not None:
            hit = [n for n, b in zip(req_names, ever) if b]
            out["req_stage"] = max((i + 1 for i, b in enumerate(ever) if b), default=0)
            out["req_names"] = hit
            out["req_ever"] = len(hit)
    except Exception:
        pass
    return out


# ---------------- ladder harvest ----------------
# 🔑 WHY EVAL IS THE RIGHT PLACE TO COLLECT THESE. Published work on this environment reports
# that no agent ever obtained HM01, which hard-blocks the third gym. Our own eval history says
# otherwise: 6 runs reached HM01 and 3 of them actually TAUGHT Cut. Every one of those runs
# measured the achievement and then threw the emulator state away, while the swarm ladder that
# exists to hand exactly such states to training workers sat empty (0 states, 0 stages). Eval
# now runs 12-16h a day, so it is the cheapest possible source of deep states -- it is already
# doing the work, it just was not keeping the artifact.
#
# 🚨 PUBLISH ONLY, NEVER ADOPT. `swarm_dir` is deliberately NOT set on the eval env: setting it
# would also arm _swarm_adopt(), and eval's entire comparability rule is that every run starts
# from init.state. Two checkpoints judged from different starting states are not being compared,
# they are being handed different games. So this writes states out by hand and nothing reads
# them back in during eval.
HARVEST_DIR = os.path.join(HERE, "ladder-harvest")
# 🚨 THIS WAS 10 AND IT HARVESTED NOTHING. The reasoning was that stage 9 (Beat Brock) is common
# enough that the agent finds it unaided, so only 10+ is worth banking. Sound in principle, wrong
# in practice: measured over a full day of continuous eval, the promoted checkpoint plateaus at
# stage 8 and the ladder stayed EMPTY -- 0 states across 0 stages. A rung nobody can reach teaches
# strictly less than a rung that is merely unambitious.
#
# 🔑 The real argument for a low threshold is BOOTSTRAPPING, which is how swarming actually works
# in the project that got furthest here: a state is banked at every objective, and runs starting
# deeper are what reach deeper still. Stage 8 skips the entire prologue -- lab, parcel, pokedex,
# pokeballs, town map, first rival -- which is where a fresh run burns most of its steps.
#
# ⚠️ Balance is kept by make_ladder's --max-per-stage, NOT by this number, so a flood of easy
# states cannot crowd out the rare deep ones. Raise this again once stage 10+ is routine.
HARVEST_MIN_STAGE = int(os.environ.get("EVAL_HARVEST_MIN_STAGE", "8"))


def harvest_state(env, stage, ckpt_name):
    """Save the emulator state so make_ladder.py can verify and install it.

    Deliberately dumb: name it, drop it, move on. make_ladder --from-dir is the thing that
    decides whether it is real -- it loads each state into a live PyBoy and reads the game's own
    flags, so a mislabelled or corrupt file is rejected there rather than trusted here.
    """
    try:
        os.makedirs(HARVEST_DIR, exist_ok=True)
        stem = os.path.basename(ckpt_name).replace(".zip", "")[:40]
        out = os.path.join(HARVEST_DIR, f"s{stage:02d}_{stem}_{uuid.uuid4().hex[:8]}.state")
        tmp = out + ".tmp"
        with open(tmp, "wb") as f:
            env.pyboy.save_state(f)
        os.replace(tmp, out)
        # 🚨 A SIDECAR WITH THE TRUE STAGE, because make_ladder cannot recover it from the state
        # alone. classify() reads get_required_events_reward(), a POINT-IN-TIME popcount -- and
        # several required flags are CLEARED by the game once their scene ends (Bill's, the
        # S.S. Anne's; see snapshot_metrics). So a state saved just after HM01 can read as FEWER
        # set flags than one saved before Bill, and the deepest states -- the whole reason this
        # harvest exists -- would be filed shallowest. Here, mid-run, we hold the cumulative mask
        # and simply know the answer. classify() still has to load the state for it to be
        # installed at all, so this supplies a number without giving up the verification.
        with open(out + ".json", "w", encoding="utf-8") as f:
            json.dump({"stage": int(stage), "checkpoint": os.path.basename(ckpt_name)}, f)
        return out
    except Exception as e:
        # Never let collecting a bonus artifact take down a scoring run.
        print(f"    [harvest] could not save stage {stage}: {e}", flush=True)
        return None


def run_once(model, names, budget_s, step_cap, label, req_obs=False, seed=None, on_step=None,
             harvest_as=None):
    """One independent episode. Returns metrics or None if it blew up.

    🔑 `seed` MAKES THE RUN REPRODUCIBLE, which is what lets a result be VERIFIED by someone
    else rather than merely believed. Nothing here was seeded before 2026-09-05: no
    `set_random_seed`, no seed passed to `reset()`, and `red_gym_env_v2.reset()` stored its
    `seed` argument and never read it. Two runs of one checkpoint could differ by 62 maps
    against 31 -- which is honest sampling noise, but it also meant no two machines could ever
    be asked to compute the same thing and be checked against each other.

    ⚠️ A SEED IS NOT ENOUGH ON ITS OWN. The loop below is bounded by WALL CLOCK, so the same
    seed on a fast and a slow machine takes a different number of steps and diverges anyway.
    For a reproducible unit of work pass `budget_s=None` and a real `step_cap`: that makes the
    run step-exact, which is the only form two hosts can be expected to agree on. The nightly
    eval keeps using the time budget, so its history stays comparable with everything scored
    before this.

    ⚠️ Seeding does NOT make the run deterministic across ARCHITECTURES -- float ops reorder --
    which is why replica comparison has to be within one arch class (BOINC calls this
    homogeneous redundancy).
    """
    env = make_env(req_obs)
    try:
        if seed is not None:
            # Seeds python, numpy AND torch. model.predict(deterministic=False) samples from
            # torch's global RNG, so this is the one that actually decides the trajectory.
            from stable_baselines3.common.utils import set_random_seed
            set_random_seed(int(seed))
            obs, _ = env.reset(seed=int(seed))
        else:
            obs, _ = env.reset()
        t0 = time.time()
        steps = 0
        # 🚨 A CUMULATIVE OR, not an end-of-run read. Required flags LATCH and then several are
        # CLEARED by the game when their scene ends, so a checkpoint that got through Bill's
        # errand and moved on would read as never having done it. Sampled every step (17 memory
        # reads against an env step that emulates 24 frames -- unmeasurable) so a flag that is
        # set and cleared quickly cannot slip between polls.
        # ⚠️ Lives here, in eval, and NOT in the env: the env was just proved byte-identical
        # across the gamespec refactor and is not worth disturbing for a measurement.
        ever = [0] * len(getattr(env, "required_events", []))
        hi_stage = 0                       # deepest stage harvested in THIS run
        # `required_event_names` is the list of names; `required_events` is the parsed flag
        # addresses (red_gym_env_v2.py:149-150). Same length, different contents -- use the
        # former for anything a human reads.
        names_req = list(getattr(env, "required_event_names", []))
        # budget_s=None => step-exact (a reproducible work unit). Otherwise wall clock, as before.
        # 🚨 BOTH bounds are optional and both must be guarded. budget_s was already allowed to
        # be None; step_cap was not, so passing a time budget with no step cap -- the obvious
        # way to say "run for an hour, no step limit" -- died with
        # "'<' not supported between instances of 'int' and 'NoneType'" on the first tick.
        # The CLI hid it by defaulting --steps to 10 million, so only a direct caller hit it.
        while ((budget_s is None or time.time() - t0 < budget_s)
               and (step_cap is None or steps < step_cap)):
            action, _ = model.predict(obs, deterministic=False)
            obs, _r, term, trunc, _i = env.step(action)
            steps += 1
            # 🔑 Optional observer, default None so the broadcast and the box's own eval are
            # bit-identical to before. The contributor panel uses it to show the live screen.
            # ⚠️ Wrapped: a visualiser must never be able to abort a scoring run.
            if on_step is not None:
                try:
                    on_step(env, steps)
                except Exception:
                    pass
            try:
                for i, b in enumerate(env.read_required_event_bits()):
                    if b and not ever[i]:
                        ever[i] = 1
                        # A bit going 0->1 IS the moment a milestone is reached, so this is the
                        # cheapest possible trigger -- no extra reads, and the state captured is
                        # the state immediately after the achievement rather than whatever the
                        # run drifted into later.
                        if harvest_as and (i + 1) >= HARVEST_MIN_STAGE and (i + 1) > hi_stage:
                            hi_stage = i + 1
                            if harvest_state(env, hi_stage, harvest_as):
                                print(f"    [{label}] 🪜 harvested a stage-{hi_stage} state "
                                      f"({names_req[i] if i < len(names_req) else '?'})",
                                      flush=True)
                    elif b:
                        ever[i] = 1
            except Exception:
                pass
            if term or trunc:
                obs, _ = env.reset()
            if steps % 20000 == 0:
                m = snapshot_metrics(env, names, ever)
                print(f"    [{label}] {steps:>7} steps  {int(time.time()-t0):>5}s  "
                      f"badges={m['badges']} maps={m['maps']} tiles={m['tiles']} "
                      f"req={m.get('req_ever', '?')}/{len(ever)} "
                      f"stage={m.get('req_stage', '?')}", flush=True)
        m = snapshot_metrics(env, names, ever)
        m["steps"] = steps
        m["seconds"] = round(time.time() - t0, 1)
        m["steps_per_s"] = round(steps / max(1e-9, time.time() - t0), 1)
        return m
    except Exception as e:
        print(f"    [{label}] FAILED: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        try:
            env.close()
        except Exception:
            pass


def median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


class _RandomPolicy:
    """🚨 THE FLOOR. Without it, "maps=2" reads as "undertrained" — and it took a hand-rolled
    A/B to discover that a 1.47M-step checkpoint scored *below* a policy that presses buttons at
    random (2 maps / 37 tiles vs 5 maps / 393). A checkpoint that loses to this has not learned
    slowly; it has learned something actively wrong, which is a different problem with a
    different fix. Every eval batch should carry this row."""
    def __init__(self, space):
        self.space = space

    def predict(self, obs, deterministic=False):
        return self.space.sample(), None


def evaluate(ckpt, runs, budget_s, step_cap, names, seed=None, harvest=False,
             on_step=None):
    """`seed` seeds the FIRST run; run i gets seed+i, so the runs stay independent samples of
    the policy while the whole set is reproducible from one number. seed=None keeps the old
    unseeded behaviour, which is what the nightly eval uses."""
    from stable_baselines3 import PPO
    if ckpt == RANDOM_NAME:
        env = make_env(False)
        model, req_obs = _RandomPolicy(env.action_space), False
        env.close()
    else:
        req_obs = needs_required_obs(ckpt)
    if budget_s is None and step_cap is None:
        # Neither bound = an episode that never ends. Fail loudly here rather than hang
        # someone's machine until they notice hours later.
        raise ValueError("evaluate() needs a time budget or a step cap; both were None")
    budget_desc = f"{budget_s/60:g} min" if budget_s is not None else f"{step_cap:,} steps"
    print(f"\n=== {os.path.basename(ckpt)} — {runs} run(s) x {budget_desc} "
          f"[{'random baseline' if ckpt == RANDOM_NAME else ('required_events obs' if req_obs else 'legacy obs')}] ===",
          flush=True)
    if ckpt != RANDOM_NAME:
        env = make_env(req_obs)           # PPO.load wants an env to bind spaces to
        try:
            model = PPO.load(ckpt, env=env, custom_objects={'lr_schedule': 0, 'clip_range': 0,
                                                            'tensorboard_log': None})
        finally:
            try:
                env.close()
            except Exception:
                pass

    got = []
    for i in range(runs):
        r = run_once(model, names, budget_s, step_cap, f"run {i+1}/{runs}", req_obs,
                     seed=None if seed is None else int(seed) + i,
                     harvest_as=(os.path.basename(ckpt) if harvest else None),
                     on_step=on_step)
        if r:
            got.append(r)
            print(f"    [run {i+1}] badges={r['badges']} events={r['events']:.1f} "
                  f"maps={r['maps']} tiles={r['tiles']} lvls={r['levels_sum']} "
                  f"({r['steps']} steps @ {r['steps_per_s']}/s)", flush=True)
    if not got:
        return None

    all_maps = sorted({m for r in got for m in r["map_names"]})
    # Union across runs, like maps_reached_any_run: which milestones this checkpoint is capable
    # of reaching at all. The medians below say how RELIABLY it gets there, which is the
    # question for promotion; this says how far it can get, which is the question for the
    # interaction-reward experiment. Both, because they genuinely differ.
    all_req = sorted({s for r in got for s in r.get("req_names", [])})
    # ⚠️ .get with a default: a run recorded before the req fields existed, or one where the
    # read raised, must not KeyError the whole aggregation and lose the batch.
    AGG = ("badges", "events", "maps", "tiles", "levels_sum",
           "req", "req_max", "req_ever", "req_stage", "knows_cut", "cut_max")
    return {
        # 🚨 ALWAYS canonicalised with .zip. SB3 accepts a path with or without the
        # extension, so `--checkpoint .../poke_10000008_steps` records a name that
        # promote.py -- which looks for the real filename -- can never match. That is not a
        # promote bug; it is two spellings of one checkpoint.
        "checkpoint": (os.path.basename(ckpt) if os.path.basename(ckpt).endswith(".zip")
                       or ckpt == RANDOM_NAME else os.path.basename(ckpt) + ".zip"),
        # Stamped even though the results file is already per-game: filenames carry no game id
        # (`poke_1000000_steps.zip` could be either), so without this a file copied or merged by
        # hand would leave scores that look comparable across games and are not.
        "game": GAME,
        "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runs": len(got),
        # ⚠️ 0.0 means STEP-EXACT, and nothing else. auto_promote and --report both filter on
        # `budget_min >= 60.0`, so a step-bounded run is excluded from those pools by
        # construction rather than being averaged in with the hour-long runs the score history
        # is built from.
        # 🚨 Rounded to 3dp, not 1: at 1dp a `--minutes 0.01` smoke run also recorded 0.0 and
        # became indistinguishable from a step-exact one. Two different things sharing one
        # sentinel is how a filter silently starts matching the wrong rows.
        "budget_min": round(budget_s / 60, 3) if budget_s is not None else 0.0,
        # Present only when the run was reproducible. Its absence is the honest signal that this
        # result cannot be re-derived by anyone else.
        **({"seed": int(seed), "step_exact": budget_s is None} if seed is not None else {}),
        "median": {k: median([r.get(k, 0) for r in got]) for k in AGG},
        "best": {k: max(r.get(k, 0) for r in got) for k in AGG},
        "maps_reached_any_run": all_maps,
        "req_stages_any_run": all_req,
        "per_run": got,
    }


def store(entry):
    try:
        with open(RESULTS, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = []
    hist.append(entry)
    tmp = RESULTS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)
    os.replace(tmp, RESULTS)


CONTRIB_EVALS = os.path.join(HERE, "contrib_evals.json")


def contrib_hint():
    """{checkpoint: mean maps reported by volunteers}, or {} if nobody has contributed.

    🚨 ADVISORY ONLY, AND THAT IS ENFORCED BY WHERE IT IS USED. This never decides WHICH
    checkpoints are eligible and never enters a stored score -- it only breaks ties in what
    order equally-starved checkpoints get the box's own hours. A contributor who fabricates a
    number can therefore make us look at a checkpoint sooner; they cannot make us believe
    anything about it, because the box re-scores it itself and only that lands in
    eval_results.json, which is the file auto_promote reads.

    That is the whole reason contributed results live in a separate file. It makes "advisory"
    a property of the plumbing rather than a rule someone has to keep remembering.
    """
    try:
        with open(CONTRIB_EVALS, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:
        return {}
    agg = {}
    for r in rows:
        m = (r.get("metrics") or {}).get("maps")
        if isinstance(m, (int, float)):
            agg.setdefault(r.get("checkpoint", ""), []).append(float(m))
    return {k: sum(v) / len(v) for k, v in agg.items() if v}


def pooled_runs(minutes):
    """{checkpoint: TOTAL runs across every stored entry at >= `minutes` per run}.

    🔑 THIS IS THE NUMBER THAT DECIDES PROMOTION, and counting it differently from
    already_scored() is why the backlog never cleared. auto_promote.all_runs() pools every
    >=60-min run a checkpoint has ever had and needs MIN_RUNS=5 before it will consider one at
    all. already_scored() asks a different question -- "is there ONE entry of at least N runs"
    -- so a checkpoint scored once at 3x60min was marked done forever at 3 pooled runs, two
    short of ever being eligible. Measured when this was written: 27 of 56 candidates had never
    been scored at all, and only 9 of 32 scored ones had reached 5 runs.
    """
    out = {}
    try:
        with open(RESULTS, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        return out
    for e in hist:
        if e.get("budget_min", 0) >= minutes:
            out[e["checkpoint"]] = out.get(e["checkpoint"], 0) + len(e.get("per_run", []))
    return out


# How close to the best well-sampled median a checkpoint must be before it is worth SPENDING
# runs to make it judgeable. 0.85 of the best was measured to select 5 checkpoints (10 runs,
# ~10h) out of 73 -- small enough to drain quickly, which is what stops this starving coverage.
CONTENDER_FRAC = float(os.environ.get("EVAL_CONTENDER_FRAC", "0.85"))
# The reference median is taken only from checkpoints with at least this many runs. A single
# lucky run can post a median of 75; letting that set the bar would lock out real contenders.
REF_MIN_RUNS = 3


def pooled_medians(minutes):
    """{basename: median map count across every pooled run at >= `minutes`}.

    Companion to pooled_runs(): that one answers "can this be judged yet", this one answers
    "is it worth judging". Both read the same stored entries so they cannot disagree.
    """
    import statistics
    runs = {}
    try:
        with open(RESULTS, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        return {}
    for e in hist:
        if e.get("budget_min", 0) >= minutes:
            runs.setdefault(os.path.basename(e["checkpoint"]), []).extend(
                r.get("maps", 0) or 0 for r in e.get("per_run", []))
    return {k: statistics.median(v) for k, v in runs.items() if v}


def rank_queue(names, pool, med, target_runs, hint=None):
    """Order checkpoints so the queue produces DECISIONS, not merely coverage.

    🚨 THE PROBLEM THIS FIXES. Most-starved-first maximises breadth and, left alone, produces
    nothing promotable: auto_promote needs 5 pooled runs, and measured on a real backlog only
    2 of 34 scored checkpoints had ever reached it -- both of them the oldest. 34 checkpoints x
    5 runs is 170 hours against 107 runs performed in the project's whole history, so breadth
    alone never converges on an answer.

    Three tiers, strict priority:
      1. CONTENDERS  - partially scored AND scoring near the best. Finishing one converts it
                       from unjudgeable to judged, which is the only thing that can change what
                       is on air. Best median first.
      2. UNEXPLORED  - never scored. A checkpoint with no runs has no median, so it can never
                       qualify as a contender until it has been looked at once; without this
                       tier the policy would be blind to anything new. Newest first.
      3. THE REST    - most starved first, the previous behaviour.

    🔑 Tier 1 is self-draining, which is what makes strict priority safe: a contender leaves the
    tier the moment it reaches target_runs, and exploring tier 2 is what creates new ones. The
    loop is explore -> spot a promising one -> confirm it -> decide, rather than a flat sweep.
    """
    hint = hint or {}
    base = {n: os.path.basename(n) for n in names}
    have = {n: pool.get(base[n], 0) for n in names}
    todo = [n for n in names if have[n] < target_runs]

    well_sampled = [med[b] for b in med if pool.get(b, 0) >= REF_MIN_RUNS]
    ref = max(well_sampled) if well_sampled else max(med.values(), default=0.0)
    bar = ref * CONTENDER_FRAC

    contenders = [n for n in todo if have[n] > 0 and med.get(base[n], 0.0) >= bar]
    unexplored = [n for n in todo if have[n] == 0]
    rest = [n for n in todo if n not in set(contenders) and n not in set(unexplored)]

    contenders.sort(key=lambda n: -med.get(base[n], 0.0))
    # Newest first: a checkpoint nobody has looked at is likeliest to be interesting if it is
    # recent. mtime rather than the step count in the name, which restarts at 0 every run.
    unexplored.sort(key=lambda n: -(os.path.getmtime(n) if os.path.exists(n) else 0))
    rest.sort(key=lambda n: (have[n], -hint.get(base[n], 0.0)))
    return contenders + unexplored + rest, {"bar": bar, "ref": ref,
                                            "contenders": len(contenders),
                                            "unexplored": len(unexplored),
                                            "rest": len(rest)}


def already_scored(runs, minutes):
    """Names with a stored result at least as thorough as the budget we're about to spend.

    A weaker past result (a 0.4-min smoke run) must NOT count as scored — that would freeze a
    checkpoint's reputation at whatever the first cheap test happened to say.
    """
    out = set()
    try:
        with open(RESULTS, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        return out
    for e in hist:
        if e.get("runs", 0) >= runs and e.get("budget_min", 0) >= minutes:
            out.add(e["checkpoint"])
    return out


def report():
    try:
        with open(RESULTS, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        print("no results yet"); return
    print(f"{'checkpoint':<30} {'when':<21} {'n':>2} {'badges':>7} {'maps':>5} "
          f"{'tiles':>6} {'events':>7}   (median of runs)")
    print("-" * 96)
    for e in hist:
        m = e["median"]
        print(f"{e['checkpoint']:<30} {e['when']:<21} {e['runs']:>2} {m['badges']:>7} "
              f"{m['maps']:>5} {m['tiles']:>6} {m['events']:>7.1f}")
    # Deepest maps seen are the most legible "how far did it actually get"
    for e in hist[-2:]:
        print(f"\n{e['checkpoint']} reached: {', '.join(e['maps_reached_any_run'][:18])}"
              + (" …" if len(e["maps_reached_any_run"]) > 18 else ""))


_CWD = os.getcwd()          # captured at import, BEFORE main() chdirs into the game's v2 dir


def broken_checkpoints():
    """Names from experiments marked `"broken": true` in docs/checkpoint_provenance.json.

    🚨 WHY THIS EXISTS. --all was scoring every unscored candidate, including 12 from run A
    ("worse than random" — the obs change forced a retrain and clip_range=0 neutered the
    gradient) and run B ("collapsed by 20M"). At 3 runs x 60 min that is ~36 HOURS of the
    nightly window spent measuring checkpoints we already know are dead, every cycle — and it
    was actively starving a live experiment of CPU when it was found.

    ⚠️ auto_promote.py has its own BROKEN_PIPELINE list for REFUSING promotion. That is a
    different job (a promotion gate, not a scheduling hint) and is deliberately left alone here:
    it covers only 4 of these 16, so the two are not interchangeable, and quietly rewiring the
    gate that decides what goes on air is not a change to make in passing. Provenance is the
    source of truth for "which experiment was this" either way.
    """
    try:
        with open(os.path.join(HERE, "docs", "checkpoint_provenance.json"), encoding="utf-8") as f:
            prov = json.load(f)
    except Exception:
        return set()          # no provenance -> score everything, the old behaviour
    return {c for v in prov.values() if v.get("broken") for c in v.get("checkpoints", [])}


def _resolve_ckpt(p):
    """Absolute path to a checkpoint named on the command line.

    Order: absolute as given -> relative to where the user actually ran the command -> relative
    to V2 (what the nightly job passes). Raises rather than returning a path that does not
    exist, so a typo is a loud failure instead of a report full of nothing.
    """
    if os.path.isabs(p):
        return p
    for base in (_CWD, V2):
        cand = os.path.join(base, p)
        if os.path.exists(cand) or os.path.exists(cand + ".zip"):
            return cand
    raise FileNotFoundError(f"no checkpoint {p!r} under {_CWD} or {V2}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--minutes", type=float, default=60.0, help="budget PER RUN")
    ap.add_argument("--steps", type=int, default=10_000_000, help="hard per-run step cap")
    ap.add_argument("--seed", type=int, default=None,
                    help="make the runs reproducible. Run i uses seed+i, so the runs are still "
                         "independent samples but the whole set re-derives from one number. "
                         "Omit for the historical unseeded behaviour.")
    ap.add_argument("--exact-steps", action="store_true",
                    help="bound each run by --steps instead of by wall clock. Required for a "
                         "result another machine can reproduce: a time budget makes a fast host "
                         "and a slow host compute different amounts and diverge even with the "
                         "same seed. Implies you should also pass --seed.")
    ap.add_argument("--force", action="store_true", help="run even if the broadcast is live")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--harvest", action="store_true",
                    help=f"save a PyBoy state whenever a run reaches a NEW required-event stage "
                         f">= {HARVEST_MIN_STAGE}, into ladder-harvest/. These are the deep "
                         f"states the swarm ladder wants and eval was throwing away. Install "
                         f"them with: make_ladder.py --from-dir ladder-harvest")
    ap.add_argument("--until-runs", type=int, default=0, metavar="N",
                    help="score checkpoints whose POOLED run count (across every stored entry "
                         "at >= --minutes) is below N, most starved first. This is the number "
                         "auto_promote judges on -- it needs 5 -- whereas --skip-scored only "
                         "asks whether a checkpoint has been scored once. Overrides "
                         "--skip-scored when both are given.")
    ap.add_argument("--skip-scored", action="store_true",
                    help="with --all, skip checkpoints already scored at this budget or better")
    ap.add_argument("--max-ckpts", type=int, default=0, metavar="N",
                    help="with --all, evaluate at most N checkpoints (most recent first)")
    ap.add_argument("--include-broken", action="store_true",
                    help="with --all, also score checkpoints from experiments marked broken "
                         "in docs/checkpoint_provenance.json (skipped by default)")
    ap.add_argument("--random", action="store_true",
                    help="score a random-action policy — the floor every checkpoint must beat")
    ap.add_argument("--game", default=gamereg.DEFAULT_SLUG, choices=sorted(gamereg.GAMES),
                    help="which game to evaluate (default: %(default)s)")
    a = ap.parse_args()

    # Rebind the module-level bindings BEFORE anything reads them. make_env(), report() and
    # store() all consult these; setting them here keeps every call site free of a game arg.
    global GAME, V2, RESULTS
    GAME, V2, RESULTS = a.game, gamereg.get(a.game).v2, gamereg.results_file(a.game)

    if a.report:
        report(); return 0

    if broadcast_live() and not a.force:
        print("refusing: the nightly broadcast is LIVE (2 cores; an uncapped eval would drop "
              "frames on air). Wait for it to end, or pass --force.", file=sys.stderr)
        return 1

    if not gamereg.get(GAME).available():
        print(f"refusing: {GAME} has no ROM/env module yet ({gamereg.get(GAME).rom_path()})",
              file=sys.stderr)
        return 1
    sys.path.insert(0, V2)            # ABSOLUTE — the chdir below invalidates a relative path
    os.chdir(V2)                      # env paths ('../init.state') are relative to the game's v2
    import torch; torch.set_num_threads(1)

    ckpts = []
    if a.all:
        import glob
        # BOTH dirs: runs/ is what's promoted, candidates/ is what the training worker has
        # uploaded and not yet been scored. Globbing only runs/ would mean a freshly trained
        # checkpoint is never evaluated, so promote.py would permanently refuse it for having
        # no score — the pipeline would deadlock with the PC happily uploading into a void.
        #
        # 🚨 ORDER AND BUDGET MATTER, because this does not scale on its own. One night of
        # training uploads ~3 candidates; at 3 runs x 60 min each that is 9h per night ON TOP
        # of re-scoring everything already scored. Measured the first time it mattered:
        # 5 checkpoints = 15h, and it grows every night until the eval can never finish inside
        # the idle window. So: candidates NEWEST FIRST (the most-trained checkpoint of a run is
        # the one worth knowing about), then runs/, then skip and cap.
        # gamereg.candidates/promoted already return full paths newest-first, per game — so a
        # second game's uploads can never be evaluated against THIS game's env.
        # The random floor goes FIRST so that if the window runs out, the one row that makes
        # every other row interpretable is the one we definitely have.
        ckpts = [RANDOM_NAME] + gamereg.candidates(GAME) + gamereg.promoted(GAME)
        if not a.include_broken:
            dead = broken_checkpoints()
            drop = [c for c in ckpts if os.path.basename(c) in dead]
            ckpts = [c for c in ckpts if os.path.basename(c) not in dead]
            if drop:
                print(f"skipping {len(drop)} checkpoint(s) from experiments marked broken in "
                      f"docs/checkpoint_provenance.json (--include-broken to score them anyway)")
        if a.until_runs:
            # Target POOLED runs, and take the most starved first. --skip-scored asks "has this
            # been scored at all"; this asks "does it yet have enough runs to be judged", which
            # is the question auto_promote actually acts on. Starved-first means a checkpoint
            # with 0 runs is reached before one already sitting on 4.
            pool = pooled_runs(a.minutes)
            have = {c: pool.get(os.path.basename(c), 0) for c in ckpts}
            full = [c for c in ckpts if have[c] >= a.until_runs]
            # Contenders first, then unexplored, then most-starved. ONE implementation, shared
            # with the contributor scheduler in volley/server.py -- two copies of a ranking rule
            # is how the box and the volunteers end up working down different queues.
            # Volunteers' reported maps remain a TIE-BREAK only; eligibility is untouched.
            hint = contrib_hint()
            ckpts, _tiers = rank_queue(
                [c for c in ckpts if have[c] < a.until_runs],
                {os.path.basename(k): v for k, v in pool.items()},
                pooled_medians(a.minutes), a.until_runs, hint)
            if hint:
                print(f"  {len(hint)} checkpoint(s) carry volunteer scores; using them to order "
                      f"equally-starved candidates (advisory only — never stored, never promoted)")
            # ⚠️ The random floor is hoisted first ONLY when it has no runs at all. It is the row
            # that makes every other row interpretable, so having none of it is a real gap -- but
            # once it has some, starvation order is the better rule, and hoisting it ahead of a
            # checkpoint with zero runs would spend an hour re-measuring a baseline we already
            # have while something genuinely unmeasured waits.
            if RANDOM_NAME in ckpts and have.get(RANDOM_NAME, 0) == 0:
                ckpts = [RANDOM_NAME] + [c for c in ckpts if c != RANDOM_NAME]
            print(f"targeting {a.until_runs} pooled run(s) at >={a.minutes:g}min each: "
                  f"{len(ckpts)} checkpoint(s) short, {len(full)} already there")
            if ckpts:
                print(f"  queue: {_tiers['contenders']} contender(s) "
                      f"(median maps >= {_tiers['bar']:.0f}, ref {_tiers['ref']:.0f}) -> "
                      f"{_tiers['unexplored']} unexplored -> {_tiers['rest']} starved")
                print("  next: " + ", ".join(
                    f"{os.path.basename(c)}({have[c]})" for c in ckpts[:5]))
        elif a.skip_scored:
            done = already_scored(a.runs, a.minutes)
            skipped = [c for c in ckpts if os.path.basename(c) in done]
            ckpts = [c for c in ckpts if os.path.basename(c) not in done]
            if skipped:
                print(f"skipping {len(skipped)} already scored at >= {a.runs}x{a.minutes:g}min: "
                      + ", ".join(os.path.basename(s) for s in skipped))
        if a.max_ckpts and len(ckpts) > a.max_ckpts:
            print(f"capping to the {a.max_ckpts} most recent of {len(ckpts)} "
                  f"(the rest keep until the next window)")
            ckpts = ckpts[:a.max_ckpts]
    elif a.random:
        ckpts = [RANDOM_NAME]
    elif a.checkpoint:
        # 🚨 A relative path used to be joined to V2 unconditionally, so `--checkpoint
        # candidates/x.zip` typed from the repo root silently became repo/v2/candidates/x.zip,
        # failed to load, and STILL printed a normal-looking report — an eval that scored
        # nothing and looked like it worked. Resolve against the caller's cwd first (main()
        # captures it before the chdir into V2), and only then fall back to V2, which is what
        # the nightly job relies on.
        ckpts = [_resolve_ckpt(a.checkpoint)]
    if not ckpts:
        print("nothing to evaluate (--all or --checkpoint)", file=sys.stderr); return 1

    names = map_names()
    failed = []
    scored = 0
    for c in ckpts:
        # 🚨 One unloadable checkpoint must NOT abort the batch. It did exactly that once: a
        # candidate with a newer observation space raised out of evaluate(), the whole service
        # exited rc=1 after 3 seconds, and NOTHING was scored — including the checkpoints
        # queued behind it. An overnight window is too expensive to lose to one bad file.
        try:
            entry = evaluate(c, a.runs, None if a.exact_steps else a.minutes * 60,
                             a.steps, names, seed=a.seed, harvest=a.harvest)
        except Exception as e:
            print(f"  !! {os.path.basename(c)} FAILED to evaluate: {type(e).__name__}: "
                  f"{str(e)[:120]} — continuing", file=sys.stderr, flush=True)
            failed.append(os.path.basename(c))
            continue
        if entry:
            store(entry)
            scored += 1
            print(f"  -> median badges={entry['median']['badges']} "
                  f"maps={entry['median']['maps']} tiles={entry['median']['tiles']} "
                  f"req={entry['median'].get('req_ever', '?')} "
                  f"stage={entry['median'].get('req_stage', '?')}", flush=True)
    if failed:
        print(f"\n⚠️  {len(failed)} checkpoint(s) could not be evaluated: {', '.join(failed)}")
    print()
    report()
    # 🚨 Exit non-zero when NOTHING was scored. A run that evaluates zero checkpoints and still
    # prints a normal-looking report is exactly how an unattended job silently does nothing all
    # night; the report is populated from history, so it looks identical either way. Partial
    # success stays rc=0 on purpose -- one bad candidate must not fail the whole window.
    if scored == 0:
        print("nothing was scored this run", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
