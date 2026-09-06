import uuid
import json
import os
from collections import deque
from pathlib import Path

import numpy as np
from skimage.transform import downscale_local_mean
import matplotlib.pyplot as plt
from pyboy import PyBoy
#from pyboy.logger import log_level
import mediapy as media
from einops import repeat

from gymnasium import Env, spaces
from pyboy.utils import WindowEvent

try:
    import gamespec
except ImportError as _e:                                       # pragma: no cover
    # 🚨 SAY WHAT TO DO. The training PC clones UPSTREAM PokemonRedExperiments and this env
    # module is hand-copied onto it; before the GameSpec seam it was self-contained apart from
    # global_map.py, so copying one file was enough and now it is not. A bare
    # "ModuleNotFoundError: No module named 'gamespec'" a few seconds into an overnight run is
    # a genuinely bad way to find that out.
    raise ImportError(
        "gamespec.py is missing from this directory. It must sit beside red_gym_env_v2.py "
        "(alongside global_map.py) -- copy it from the box's repo/v2/. See docs/GEN2.md."
    ) from _e

# 🔑 EVERY RAM ADDRESS AND MAP LAYOUT NOW COMES FROM `self.gspec` (gamespec.py). They used to be
# module literals and inline hex spread over 25 call sites, several of them duplicated -- the six
# level addresses appeared three times, the party-count address four -- so a second game could
# only be supported by forking this file. See gamespec.py for the full reasoning and for which
# two Gen 2 differences are structural (map identity is a PAIR; badges span two bytes) rather
# than merely a different constant.
#
# ⚠️ The refactor was verified INERT, not reviewed: tests/spec_snapshot.py fingerprints every
# accessor, the whole reward decomposition and every observation array from two save states, and
# the before/after files are identical. Keep it that way -- re-run it after touching anything
# here that reads memory.

# 🚨 CRITICAL-PATH EVENTS (spec.required_events_file). get_all_events_reward() is a popcount over
# the whole flag range, so every one of the ~2,558 flags is worth exactly the same: "opened a
# menu" scores what "Beat Brock" scores. Measured on our best eval run (tiles 9228 / events 103 /
# badges 1, at reward_scale 0.5, explore_weight 0.25) the decomposition was event 206.0 / explore
# 115.4 / badge 5.0 -- i.e. beating the first gym leader was 1.5% of return, about 2.5 generic
# flags. The agent was optimising exactly what we wrote down.
#
# Pleines et al. (arXiv 2502.19920) studied THIS env and found the ceiling: Misty 27%, Bill's
# quest 19%, and HM01 obtained by no agent ever -- which hard-blocks gym 3 behind a cuttable
# tree. thatguy11325/pokemonred_puffer, which did beat the game, splits required_event (7.13)
# from event (0.727): a ~10:1 premium WITHIN events. Ours was 1:1. That gap is what this fixes.
#
# ⚠️ Bounded by construction: this list is finite and each flag latches once, so the term can
# never run away the way an unbounded additive term does.

# 🚨 UNBOUNDED PER-STEP LIST -> WORKER OOM. append_agent_stats() pushes a ~16-key dict on EVERY
# step and nothing trims it until reset() — which is `max_steps` away, i.e. 163,840 steps. At
# roughly 1.3 KB per entry that is ~210 MB per env per episode, ~5 GB across 24 workers, growing
# continuously. Measured symptom: fps decaying monotonically (3766 -> 3224 over nine PPO
# iterations) and then a worker killed mid-step, surfacing as BrokenPipeError [WinError 109] /
# EOFError from SubprocVecEnv — which reads like an IPC fault and is really an out-of-memory kill.
#
# 🔑 The ONLY reader is tensorboard_callback.py, and it takes `stats[-1]` — the last entry alone.
# So a bounded deque loses nothing: same API (append, [-1], len), constant memory.
# ⚠️ The broadcast inherits this too: nightly.py subclasses RedGymEnv and runs for hours.
AGENT_STATS_MAX = int(os.environ.get("AGENT_STATS_MAX", "256"))

class RedGymEnv(Env):
    def __init__(self, config=None):
        # 🚨 FIRST, before anything else touches memory or builds a space. The observation space
        # is sized from gspec.n_event_bits / gspec.n_badge_bits, and the world canvas from
        # gspec.world() -- a spec set later would build a space that does not match the reads.
        # ⚠️ Defaults to red, so every existing caller (nightly.py, eval_checkpoint.py,
        # train_worker.py, smoke.py, capture.py) is unchanged and keeps loading its checkpoints.
        #
        # 🚨 NAMED `gspec`, NOT `spec`, AND THAT IS NOT COSMETIC. gymnasium.Env declares
        # `spec: EnvSpec | None = None` as part of its public API, and SB3's Monitor does
        # `env.spec.id if env.spec is not None else None`. Shadowing it with a GameSpec (which
        # has no `.id`) turns any Monitor constructed WITH a filename into an AttributeError --
        # and nothing here passes a filename today, so it would have sat silent until somebody
        # enabled monitor logging on the training run. Env.__str__ reads it too.
        self.gspec = gamespec.get(config.get("game", "red"))
        self.world = self.gspec.world()
        self.s_path = config["session_path"]
        self.save_final_state = config["save_final_state"]
        self.print_rewards = config["print_rewards"]
        self.headless = config["headless"]
        self.init_state = config["init_state"]
        self.act_freq = config["action_freq"]
        self.max_steps = config["max_steps"]
        self.save_video = config["save_video"]
        self.fast_video = config["fast_video"]
        self.frame_stacks = 3
        self.explore_weight = (
            1 if "explore_weight" not in config else config["explore_weight"]
        )
        self.reward_scale = (
            1 if "reward_scale" not in config else config["reward_scale"]
        )
        self.instance_id = (
            str(uuid.uuid4())[:8]
            if "instance_id" not in config
            else config["instance_id"]
        )
        self.s_path.mkdir(exist_ok=True)
        self.full_frame_writer = None
        self.model_frame_writer = None
        self.map_frame_writer = None
        self.reset_count = 0
        self.all_runs = []

        self.essential_map_locations = self.gspec.map_progress

        # Set this in SOME subclasses
        self.metadata = {"render.modes": []}
        self.reward_range = (0, 15000)

        self.valid_actions = [
            WindowEvent.PRESS_ARROW_DOWN,
            WindowEvent.PRESS_ARROW_LEFT,
            WindowEvent.PRESS_ARROW_RIGHT,
            WindowEvent.PRESS_ARROW_UP,
            WindowEvent.PRESS_BUTTON_A,
            WindowEvent.PRESS_BUTTON_B,
            WindowEvent.PRESS_BUTTON_START,
        ]

        self.release_actions = [
            WindowEvent.RELEASE_ARROW_DOWN,
            WindowEvent.RELEASE_ARROW_LEFT,
            WindowEvent.RELEASE_ARROW_RIGHT,
            WindowEvent.RELEASE_ARROW_UP,
            WindowEvent.RELEASE_BUTTON_A,
            WindowEvent.RELEASE_BUTTON_B,
            WindowEvent.RELEASE_BUTTON_START
        ]

        # load event names (parsed from https://github.com/pret/pokered/blob/91dc3c9f9c8fd529bb6e8307b58b96efa0bec67e/constants/event_constants.asm)
        with open(self.gspec.events_file) as f:
            event_names = json.load(f)
        self.event_names = event_names

        # Curated critical path. Parsed ONCE into (addr, bit) pairs -- read_bit() runs on every
        # step for every entry, and re-parsing "0xD74B-2" 17 times a step is pure waste.
        with open(self.gspec.required_events_file) as f:
            required = json.load(f)
        self.required_event_names = [e["name"] for e in required]
        self.required_events = [
            (int(e["flag"].split("-")[0], 16), int(e["flag"].split("-")[1]))
            for e in required
        ]

        self.output_shape = (72, 80, self.frame_stacks)
        self.coords_pad = 12

        # Set these in ALL subclasses
        self.action_space = spaces.Discrete(len(self.valid_actions))
        
        self.enc_freqs = 8

        # 🚨 OFF BY DEFAULT, and this is not timidity -- it is what keeps the stream alive.
        # Adding a key to the observation space makes every EXISTING checkpoint unloadable
        # ("Observation spaces do not match"), and nightly.py loads poke_26214400.zip against
        # this same env every night at 01:00 UTC. Flipping this on unconditionally would have
        # taken the broadcast down tonight. Training opts IN; the broadcast never does, so it
        # keeps running the old policy until a new one is trained and promoted.
        # ⚠️ The REWARD changes need no such gate: nightly.py only calls model.predict(), so
        # rewards are computed and discarded at inference. Only the obs space is load-bearing.
        self.required_events_obs = bool(config.get("required_events_obs", False))
        # 🔑 MEASURED, not chosen. Under a trained policy the interaction-point count settles at
        # ~0.094 of the tile count (stable from 6k steps to 12k). Explore pays 0.1/tile, so
        # 0.25 * 0.1 / 0.094 = 0.27 makes interactions worth about a quarter of exploration.
        # My first guess of 1.0 made them 2.2x explore -- dominant, which is the failure mode
        # Pleines et al. document for an over-weighted navigation reward.
        # 0.0 disables the term entirely, for a clean A/B.
        #
        # 🚨 THE A/B RETURNED A NULL, AND THE TERM IS KEPT ON PURPOSE. Measured 2026-09-01:
        # 8 step-capped runs per arm at 260k steps, matched at 10M/20M/25M training steps.
        # Deep-run rate (required-event stage >= 10) was 3/8 for BOTH arms; the control was
        # slightly ahead on medians and ceiling. Frank's call (2026-09-02): "it might show a
        # benefit later; if it doesn't matter either way, keep it in."
        # ⚠️ DO NOT DELETE THIS ON THE STRENGTH OF THAT RESULT. It is a null, not a negative --
        # 3/8 vs 3/8 with near-bimodal outcomes rules out a LARGE effect and nothing smaller.
        # The HM01 chain is entirely dialogue, so the term points at the right failure mode.
        # ⚠️ It is not free either: it takes ~10% of return by design, and it is now part of the
        # baseline, so every later experiment inherits it as a confound. Full numbers and the
        # reasoning are in docs/checkpoint_provenance.json under experiment D.
        self.interact_weight = float(config.get("interact_weight", 0.27))

        # 🔑 MAP PROGRESS AS A REWARD. max_map_progress has been computed on every step since the
        # original project and paid nothing — it went to agent_stats and no further. It is the
        # rank of the furthest map along a hand-authored critical path, so it is a positional
        # proxy for "how far through the game are you", and it fills the long gaps between
        # required events with something an agent can actually walk toward.
        #
        # 🚨 Weight SIZED FROM REAL RUNS, not chosen. Reconstructed the decomposition of a stored
        # stage-16 run (9,126 tiles, 90 generic events, 13 required, 1 badge, reward_scale 0.5,
        # explore_weight 0.25): event 67.5 / required 97.5 / explore 114.1 / interact 29.0 /
        # badge 10, total ~318. At 4.0 the term contributes 0.5*23*4 = 46, about 13% of return
        # and comfortably below `required` at 31%. In tile terms one map rank is worth ~160 tiles
        # of exploration where one required event is worth ~600 — arriving somewhere should pay
        # less than finishing what you went there for.
        # ⚠️ Bounded by construction: the path has a fixed length and the value ratchets, so this
        # term cannot run away the way an unbounded additive term can.
        self.map_weight = float(config.get("map_weight", 4.0))

        # ── SWARMING ────────────────────────────────────────────────────────────────────
        # When any worker clears a new required-event stage it drops its emulator state in a
        # shared directory; other workers adopt it on reset. One env's lucky breakthrough
        # becomes every env's starting point, which is the single technique the only project
        # to finish this game credits for getting past the mid-game gates.
        #
        # 🚨 DISABLED unless `swarm_dir` is set. The nightly broadcast loads this same env and
        # must never pick up training behaviour -- same discipline as required_events_obs.
        # It changes no observation and no reward, so checkpoints stay loadable either way.
        self.swarm_dir = config.get("swarm_dir")
        self.swarm_p = float(config.get("swarm_p", 0.75))
        # How often an adopting episode starts at the DEEPEST known point rather than a
        # randomly chosen one. Organic swarming wants the frontier pushed; a demonstration
        # ladder wants every segment practised. One knob covers both, because with only a
        # handful of stages (early organic discovery) "uniform" is already near the frontier.
        self.swarm_frontier_p = float(config.get("swarm_frontier_p", 0.3))
        if self.swarm_dir:
            self.swarm_dir = Path(self.swarm_dir)
            self.swarm_dir.mkdir(parents=True, exist_ok=True)
        self.swarm_loaded_stage = 0

        obs_space = {}
        if self.required_events_obs:
            obs_space["required_events"] = spaces.MultiBinary(len(self.required_events))

        self.observation_space = spaces.Dict(
            {
                **obs_space,
                "screens": spaces.Box(low=0, high=255, shape=self.output_shape, dtype=np.uint8),
                "health": spaces.Box(low=0, high=1),
                "level": spaces.Box(low=-1, high=1, shape=(self.enc_freqs,)),
                # 🚨 Both widths come from the spec: Gen 2 has 16 badges across two bytes and a
                # different flag range, and both are OBSERVATION SPACE changes -- which is
                # exactly why a Crystal policy can never share a checkpoint directory with Red.
                "badges": spaces.MultiBinary(self.gspec.n_badge_bits),
                "events": spaces.MultiBinary(self.gspec.n_event_bits),
                "map": spaces.Box(low=0, high=255, shape=(
                    self.coords_pad*4,self.coords_pad*4, 1), dtype=np.uint8),
                "recent_actions": spaces.MultiDiscrete([len(self.valid_actions)] * self.frame_stacks)
            }
        )

        head = "null" if config["headless"] else "SDL2"

        #log_level("ERROR")
        self.pyboy = PyBoy(
            config["gb_path"],
            #debugging=False,
            #disable_input=False,
            window=head,
            # 🚨 Off for TRAINING, on for the BROADCAST -- they want opposite things.
            # Training is headless and nothing ever drains the sample buffer, so newer PyBoy
            # fills it and never empties it -> "pyboy.core.sound CRITICAL Buffer overrun!
            # 1602 of 1602" once per tick, which buries every real log line (and the overrun
            # path indexes past the buffer, so it is not purely cosmetic). Disabling the
            # emulation outright -- not just the volume -- stops it and is a small speed win.
            # The stream DOES want audio, so nightly.py's StreamEnv passes True.
            # ⚠️ Default False: a caller that forgets is a spammy training run, not a silent
            # stream, and the stream is the one place that would notice immediately.
            sound_emulated=bool(config.get("sound_emulated", False)),
        )

        #self.screen = self.pyboy.botsupport_manager().screen()

        if not config["headless"]:
            self.pyboy.set_emulation_speed(6)

    def reset(self, seed=None, options={}):
        self.seed = seed
        # 🔑 ACTUALLY SEED THE RNG. `self.seed = seed` above stored the argument and nothing in
        # this file ever read it again, so passing a seed did nothing at all. The env's only
        # randomness is `self.np_random` in _swarm_adopt(), which gymnasium creates lazily with
        # an OS-random seed on first access -- so swarm adoption was irreproducible even when a
        # caller thought it had pinned the run.
        #
        # ⚠️ Deliberately safe for the broadcast: gymnasium.Env.reset documents that with
        # seed=None "the RNG is not reset". nightly.py and every pre-2026-09-05 eval call
        # reset() with no seed, so for them this line is a no-op and behaviour is unchanged.
        # It only bites when someone asks for a specific seed, which is the point.
        super().reset(seed=seed)
        # restart game, skipping credits
        with open(self.init_state, "rb") as f:
            self.pyboy.load_state(f)

        # 🔑 Swarm adoption happens HERE, before any baseline is taken. base_event_flags and
        # base_required_flags are read from whatever state the emulator holds a few lines
        # below, so adopting after they were computed would hand the agent a large one-off
        # reward at t=0 for progress somebody else made -- exactly the failure the baselining
        # was written to prevent. Ordering is the whole safeguard.
        self._swarm_adopt()

        self.init_map_mem()

        self.agent_stats = deque(maxlen=AGENT_STATS_MAX)

        self.explore_map_dim = self.world.shape
        self.explore_map = np.zeros(self.explore_map_dim, dtype=np.uint8)

        self.recent_screens = np.zeros( self.output_shape, dtype=np.uint8)
        
        self.recent_actions = np.zeros((self.frame_stacks,), dtype=np.uint8)

        self.levels_satisfied = False
        self.base_explore = 0
        self.max_opponent_level = 0
        self.max_event_rew = 0
        self.max_required_rew = 0
        self.max_cut_rew = 0
        self.max_level_rew = 0
        self.last_health = 1
        self.total_healing_rew = 0
        self.died_count = 0
        self.party_size = 0
        self.step_count = 0

        self.base_event_flags = self.gspec.event_popcount(self.read_m)

        # ⚠️ Baselined like base_event_flags, and for a reason that is INERT TODAY but will not
        # stay that way: training always resets to init.state, where this is 0. The moment a
        # run resumes a mid-game save -- the broadcast already does, and swarming would make it
        # the norm -- an un-baselined count pays a large one-off reward at t=0 for progress the
        # agent did not make. Measuring progress made THIS episode is the honest version.
        # (`cut` and `badge` are deliberately NOT baselined: those are capability milestones,
        # and badge has always worked that way -- keeping two conventions, not inventing a third.)
        self.base_required_flags = self.get_required_events_reward()

        # ⚠️ Baselined for the same reason as base_required_flags, and it matters MORE here.
        # max_map_progress is derived from where the player is STANDING, so an episode resuming a
        # mid-game save reads a high rank on its very first step and would bank the whole thing as
        # progress it did not make. Training from init.state this is 0, but the broadcast already
        # resumes, and swarm adoption makes a mid-game start the norm — which is exactly when a
        # positional reward is most tempting to hand out for free.
        # (`badge` and `cut` stay un-baselined on purpose: those are capability milestones, and
        # badge has always worked that way. Two conventions, not a third.)
        self.base_map_progress = max(self.get_map_progress(self.gspec.map_id(self.read_m)), 0)

        self.current_event_flags_set = {}

        # experiment! 
        # self.max_steps += 128

        self.max_map_progress = 0
        self.progress_reward = self.get_game_state_reward()
        self.total_reward = sum([val for _, val in self.progress_reward.items()])
        self.reset_count += 1
        return self._get_obs(), {}

    def init_map_mem(self):
        self.seen_coords = {}
        # Places where a dialogue box was OPENED. See update_seen_interactions().
        self.seen_interactions = set()
        self._box_open = False

    def render(self, reduce_res=True):
        game_pixels_render = self.pyboy.screen.ndarray[:,:,0:1]  # (144, 160, 3)
        if reduce_res:
            game_pixels_render = (
                downscale_local_mean(game_pixels_render, (2,2,1))
            ).astype(np.uint8)
        return game_pixels_render
    
    def _get_obs(self):
        
        screen = self.render()

        self.update_recent_screens(screen)
        
        # normalize to approx 0-1
        level_sum = 0.02 * sum(self.gspec.levels(self.read_m))

        observation = {
            "screens": self.recent_screens,
            "health": np.array([self.read_hp_fraction()]),
            "level": self.fourier_encode(level_sum),
            "badges": self.gspec.badge_bits(self.read_m),
            "events": np.array(self.read_event_bits(), dtype=np.int8),
            "map": self.get_explore_map()[:, :, None],
            "recent_actions": self.recent_actions
        }

        # Must mirror the observation_space gate above exactly, or SB3 fails on a key mismatch.
        if self.required_events_obs:
            observation["required_events"] = self.read_required_event_bits()

        return observation

    def step(self, action):

        if self.save_video and self.step_count == 0:
            self.start_video()

        self.run_action_on_emulator(action)
        self.append_agent_stats(action)

        self.update_recent_actions(action)

        self.update_seen_coords()

        # ⚠️ Takes the ACTION so START can be excluded. `action` here is an index into
        # valid_actions, so map it before comparing to a WindowEvent.
        self.update_seen_interactions(self.valid_actions[action]
                                      if action < len(self.valid_actions) else None)

        self.update_explore_map()

        self.update_heal_reward()

        self.party_size = self.gspec.party_count(self.read_m)

        new_reward = self.update_reward()

        self.last_health = self.read_hp_fraction()

        self.update_map_progress()

        step_limit_reached = self.check_if_done()

        obs = self._get_obs()

        # self.save_and_print_info(step_limit_reached, obs)

        # create a map of all event flags set, with names where possible
        #if step_limit_reached:
        if self.step_count % 100 == 0:
            for address in range(self.gspec.event_flags_start, self.gspec.event_flags_end):
                val = self.read_m(address)
                for idx, bit in enumerate(f"{val:08b}"):
                    if bit == "1":
                        # TODO this currently seems to be broken!
                        key = f"0x{address:X}-{idx}"
                        if key in self.event_names.keys():
                            self.current_event_flags_set[key] = self.event_names[key]
                        else:
                            print(f"could not find key: {key}")

        self.step_count += 1

        return obs, new_reward, False, step_limit_reached, {}
    
    def run_action_on_emulator(self, action):
        # press button then release after some steps
        self.pyboy.send_input(self.valid_actions[action])
        # disable rendering when we don't need it
        render_screen = self.save_video or not self.headless
        press_step = 8
        self.pyboy.tick(press_step, render_screen)
        self.pyboy.send_input(self.release_actions[action])
        self.pyboy.tick(self.act_freq - press_step - 1, render_screen)
        self.pyboy.tick(1, True)
        if self.save_video and self.fast_video:
            self.add_video_frame()
        
    def append_agent_stats(self, action):
        x_pos, y_pos, map_n = self.get_game_coords()
        levels = self.gspec.levels(self.read_m)
        self.agent_stats.append(
            {
                "step": self.step_count,
                "x": x_pos,
                "y": y_pos,
                "map": map_n,
                "max_map_progress": self.max_map_progress,
                "last_action": action,
                "pcount": self.gspec.party_count(self.read_m),
                "levels": levels,
                "levels_sum": sum(levels),
                "ptypes": self.read_party(),
                "hp": self.read_hp_fraction(),
                "coord_count": len(self.seen_coords),
                "deaths": self.died_count,
                "badge": self.get_badges(),
                "event": self.progress_reward["event"],
                "healr": self.total_healing_rew,
            }
        )

    def start_video(self):

        if self.full_frame_writer is not None:
            self.full_frame_writer.close()
        if self.model_frame_writer is not None:
            self.model_frame_writer.close()
        if self.map_frame_writer is not None:
            self.map_frame_writer.close()

        base_dir = self.s_path / Path("rollouts")
        base_dir.mkdir(exist_ok=True)
        full_name = Path(
            f"full_reset_{self.reset_count}_id{self.instance_id}"
        ).with_suffix(".mp4")
        model_name = Path(
            f"model_reset_{self.reset_count}_id{self.instance_id}"
        ).with_suffix(".mp4")
        self.full_frame_writer = media.VideoWriter(
            base_dir / full_name, (144, 160), fps=60, input_format="gray"
        )
        self.full_frame_writer.__enter__()
        self.model_frame_writer = media.VideoWriter(
            base_dir / model_name, self.output_shape[:2], fps=60, input_format="gray"
        )
        self.model_frame_writer.__enter__()
        map_name = Path(
            f"map_reset_{self.reset_count}_id{self.instance_id}"
        ).with_suffix(".mp4")
        self.map_frame_writer = media.VideoWriter(
            base_dir / map_name,
            (self.coords_pad*4, self.coords_pad*4), 
            fps=60, input_format="gray"
        )
        self.map_frame_writer.__enter__()

    def add_video_frame(self):
        self.full_frame_writer.add_image(
            self.render(reduce_res=False)[:,:,0]
        )
        self.model_frame_writer.add_image(
            self.render(reduce_res=True)[:,:,0]
        )
        self.map_frame_writer.add_image(
            self.get_explore_map()
        )

    def get_game_coords(self):
        """(x, y, map_id).

        🚨 STRUCTURAL, not just an address swap. Gen 1 identifies a map with one byte; Gen 2
        needs the (group, number) PAIR, because group 1 map 3 and group 2 map 3 are different
        places. A port that read only the number would silently merge maps -- corrupting the
        coord set, the explore map and map progress all at once, with no error anywhere.
        `spec.coords` returns a packed id so everything downstream still gets one hashable value.
        """
        return self.gspec.coords(self.read_m)

    # Rows 104-136 of the 144-row screen, x 8-152. Calibrated against a captured frame, not
    # assumed: with no dialogue that band sits at the palette floor (~19-85) and a text box
    # fills it uniformly at ~249.
    DIALOG_ROWS = (104, 136, 8, 152)
    DIALOG_THRESH = 200

    def _dialog_open(self):
        r0, r1, c0, c1 = self.DIALOG_ROWS
        return float(self.pyboy.screen.ndarray[r0:r1, c0:c1, :3].mean()) > self.DIALOG_THRESH

    def update_seen_interactions(self, action):
        """Count novel places where the player OPENED a dialogue box.

        🔑 Why this exists: the exploration reward counts distinct tiles, so anything that does
        not move you is worth nothing — talking, reading a sign, taking an item. Every stage of
        the HM01 chain (Bill, the cell separator, the S.S. ticket, HM01 itself) is exactly that,
        which is a blind spot precisely where the hard gate is.

        🚨 It counts the no-box -> box TRANSITION, not the box being present. A dialogue stays up
        for many steps while text advances, so "a box is visible" fires for whatever button
        happened to be pressed — measured at 42% for `up`, as often as `a`. The transition is
        what means "an interaction just started here."

        🚨 START is excluded. It opens the menu ANYWHERE, and measured highest of all buttons
        (13.2% of presses opened a box, vs 9.7% for A). Without that exclusion the agent could
        farm this reward at every tile, which is the exact failure mode Pleines et al. document
        for the healing reward.

        ⚠️ A HEURISTIC, and known imperfect. No single RAM byte tracks the dialogue state across
        game states — wTextBoxID agrees with the screen only 43% of the time, and the best
        empirical candidate (0xCFC4) is perfect in the opening and 66% hours in. The screen is
        the reliable signal available. Expect some false positives from menus reached without
        START, and misses when a dialogue opens without a visible box.
        """
        now = self._dialog_open()
        opened = now and not self._box_open
        self._box_open = now
        # Battles are excluded for the same reason seen_coords excludes them: battle text would
        # otherwise credit every patch of grass.
        if (opened and action != WindowEvent.PRESS_BUTTON_START
                and not self.gspec.in_battle(self.read_m)):
            x_pos, y_pos, map_n = self.get_game_coords()
            self.seen_interactions.add(f"x:{x_pos} y:{y_pos} m:{map_n}")

    def update_seen_coords(self):
        # if not in battle
        if not self.gspec.in_battle(self.read_m):
            x_pos, y_pos, map_n = self.get_game_coords()
            coord_string = f"x:{x_pos} y:{y_pos} m:{map_n}"
            if coord_string in self.seen_coords.keys():
                self.seen_coords[coord_string] += 1
            else:
                self.seen_coords[coord_string] = 1
            #self.seen_coords[coord_string] = self.step_count

    def get_current_coord_count_reward(self):
        x_pos, y_pos, map_n = self.get_game_coords()
        coord_string = f"x:{x_pos} y:{y_pos} m:{map_n}"
        if coord_string in self.seen_coords.keys():
            count = self.seen_coords[coord_string]
        else:
            count = 0
        return 0 if count < 600 else 1

    def get_global_coords(self):
        x_pos, y_pos, map_n = self.get_game_coords()
        return self.world.to_global(y_pos, x_pos, map_n)

    def update_explore_map(self):
        c = self.get_global_coords()
        if c[0] >= self.explore_map.shape[0] or c[1] >= self.explore_map.shape[1]:
            print(f"coord out of bounds! global: {c} game: {self.get_game_coords()}")
            pass
        else:
            self.explore_map[c[0], c[1]] = 255

    def get_explore_map(self):
        """A coords_pad*2 square of the visited-map, centred on the player, upscaled 2x.

        🚨 THIS FUNCTION HAS CRASHED TWO WORKERS with a Windows access violation -- once via
        einops.repeat -> np.tile, once via plain ndarray.repeat. Two different NumPy calls, one
        shared input: a NON-CONTIGUOUS strided VIEW into explore_map. So the view is the suspect,
        not either function. Three changes below, all cheap:

          1. Indices are CLAMPED rather than sliced raw. The old guard checked only the upper
             bound, so a global coord below coords_pad (12) would slice with a NEGATIVE start,
             which numpy wraps from the end and silently yields a (0, 24) array instead of
             (24, 24). Unreachable today -- local_to_global floors at PAD=20 -- but it is one
             bad map_data entry away from being reachable, and it fails silently.
          2. The result is COPIED into a fresh contiguous buffer, so the repeat operates on
             owned contiguous memory rather than a strided view of a long-lived array.
          3. The shape is ASSERTED. A wrong shape becomes a Python error naming this function,
             not a malformed observation that dies later in native code.
        """
        c = self.get_global_coords()
        h, w = self.explore_map.shape
        pad = self.coords_pad
        out = np.zeros((pad * 2, pad * 2), dtype=np.uint8)
        y0, y1 = max(0, c[0] - pad), min(h, c[0] + pad)
        x0, x1 = max(0, c[1] - pad), min(w, c[1] + pad)
        if y1 > y0 and x1 > x0:
            # Copy into the correctly-offset slot, so an edge-of-map view stays 24x24 and is
            # padded with zeros rather than coming back short.
            out[(y0 - (c[0] - pad)):(y1 - (c[0] - pad)),
                (x0 - (c[1] - pad)):(x1 - (c[1] - pad))] = self.explore_map[y0:y1, x0:x1]
        if out.shape != (pad * 2, pad * 2):
            raise RuntimeError(f"explore map slice is {out.shape}, expected "
                               f"{(pad*2, pad*2)} at global {c}")
        # ⚠️ Was `repeat(out, 'h w -> (h h2) (w w2)', h2=2, w2=2)` (einops). Identical output —
        # verified element-wise — but 3.6x faster, and it drops einops from the hottest path in
        # the env: this runs on EVERY step of every worker.
        #
        # It is also a deliberate experiment. A worker died here with a Windows access violation
        # whose faulthandler stack was get_explore_map -> einops.repeat -> np.tile, on a 14900K.
        # The out-of-bounds theories were checked and are wrong: PAD(20) > coords_pad(12), so no
        # reachable coordinate produces a short slice (verified over every map's corners), and
        # local_to_global already clamps to the map centre. So the crash is inside NumPy on a
        # valid 24x24 array — which points at the toolchain or the CPU, not at this code.
        # Taking a different NumPy code path tells us which: if the crash moves elsewhere it was
        # never about this line.
        # 🚨 A THIRD NUMPY PATH, because this line has now crashed FOUR workers with a Windows
        # access violation on a 24x24 contiguous uint8 array: once via einops.repeat -> np.tile,
        # then three times via ndarray.repeat (2026-08-28, 09-02, 09-03). The comment that used
        # to sit here framed switching to ndarray.repeat as an experiment -- "if the crash moves
        # elsewhere it was never about this line". It did not move. It is this line.
        #
        # ⚠️ AND WORKER COUNT IS NOT THE VARIABLE, contrary to what this file previously claimed.
        # "8 completes, 16 and 24 die" was falsified on 2026-09-03: a run at --envs 8 crashed
        # here after 11 minutes. The traceback's line numbers matched this exact file, so it was
        # genuinely this code at genuinely 8 workers.
        #
        # Strided assignment is a different code path from repeat's ufunc machinery. Verified
        # BIT-IDENTICAL over 2000 random arrays and 35% faster (0.0056 vs 0.0085 ms).
        # ⚠️ HONEST STATUS: this is a HEDGE, not a diagnosis. The real suspect is the platform --
        # Python 3.14 with cp314 NumPy wheels, on a CPU that has also thrown ILLEGAL INSTRUCTION
        # (0xc000001d) from _multiarray_umath. If numpy's SIMD dispatch is at fault, the crash
        # will simply reappear somewhere else, and the fix is NPY_DISABLE_CPU_FEATURES or a
        # Python 3.12 environment, not this line.
        big = np.zeros((out.shape[0] * 2, out.shape[1] * 2), dtype=np.uint8)
        big[0::2, 0::2] = out
        big[1::2, 0::2] = out
        big[0::2, 1::2] = out
        big[1::2, 1::2] = out
        return big
    
    def update_recent_screens(self, cur_screen):
        self.recent_screens = np.roll(self.recent_screens, 1, axis=2)
        self.recent_screens[:, :, 0] = cur_screen[:,:, 0]

    def update_recent_actions(self, action):
        self.recent_actions = np.roll(self.recent_actions, 1)
        self.recent_actions[0] = action

    def update_reward(self):
        # compute reward
        self.progress_reward = self.get_game_state_reward()
        new_total = sum(
            [val for _, val in self.progress_reward.items()]
        )
        new_step = new_total - self.total_reward

        self.total_reward = new_total
        return new_step

    def group_rewards(self):
        prog = self.progress_reward
        # these values are only used by memory
        return (
            prog["level"] * 100 / self.reward_scale,
            self.read_hp_fraction() * 2000,
            prog["explore"] * 150 / (self.explore_weight * self.reward_scale),
        )

    def check_if_done(self):
        done = self.step_count >= self.max_steps - 1
        # done = self.read_hp_fraction() == 0 # end game on loss
        return done

    def save_and_print_info(self, done, obs):
        if self.print_rewards:
            prog_string = f"step: {self.step_count:6d}"
            for key, val in self.progress_reward.items():
                prog_string += f" {key}: {val:5.2f}"
            prog_string += f" sum: {self.total_reward:5.2f}"
            print(f"\r{prog_string}", end="", flush=True)

        if self.step_count % 50 == 0:
            plt.imsave(
                self.s_path / Path(f"curframe_{self.instance_id}.jpeg"),
                self.render(reduce_res=False)[:,:, 0],
            )

        if self.print_rewards and done:
            print("", flush=True)
            if self.save_final_state:
                fs_path = self.s_path / Path("final_states")
                fs_path.mkdir(exist_ok=True)
                plt.imsave(
                    fs_path
                    / Path(
                        f"frame_r{self.total_reward:.4f}_{self.reset_count}_explore_map.jpeg"
                    ),
                    obs["map"][:,:, 0],
                )
                plt.imsave(
                    fs_path
                    / Path(
                        f"frame_r{self.total_reward:.4f}_{self.reset_count}_full_explore_map.jpeg"
                    ),
                    self.explore_map,
                )
                plt.imsave(
                    fs_path
                    / Path(
                        f"frame_r{self.total_reward:.4f}_{self.reset_count}_full.jpeg"
                    ),
                    self.render(reduce_res=False)[:,:, 0],
                )

        if self.save_video and done:
            self.full_frame_writer.close()
            self.model_frame_writer.close()
            self.map_frame_writer.close()

    def read_m(self, addr):
        #return self.pyboy.get_memory_value(addr)
        return self.pyboy.memory[addr]

    def read_bit(self, addr, bit: int) -> bool:
        # add padding so zero will read '0b100000000' instead of '0b0'
        return bin(256 + self.read_m(addr))[-bit - 1] == "1"

    def read_event_bits(self):
        return self.gspec.event_bits(self.read_m)

    def get_levels_sum(self):
        min_poke_level = 2
        starter_additional_levels = 4
        poke_levels = [
            max(lvl - min_poke_level, 0) for lvl in self.gspec.levels(self.read_m)
        ]
        return max(sum(poke_levels) - starter_additional_levels, 0)

    def get_levels_reward(self):
        explore_thresh = 22
        scale_factor = 4
        level_sum = self.get_levels_sum()
        if level_sum < explore_thresh:
            scaled = level_sum
        else:
            scaled = (level_sum - explore_thresh) / scale_factor + explore_thresh
        self.max_level_rew = max(self.max_level_rew, scaled)
        return self.max_level_rew

    def get_badges(self):
        return self.gspec.badge_count(self.read_m)

    def read_party(self):
        return self.gspec.party_species(self.read_m)

    def get_all_events_reward(self):
        # adds up all event flags, minus any the spec excludes (Gen 1's museum ticket is set at
        # the start of the game and is not progress)
        return max(
            self.gspec.event_popcount(self.read_m)
            - self.base_event_flags
            - self.gspec.excluded_event_count(self.read_m),
            0,
        )

    def read_required_event_bits(self):
        return np.array([int(self.read_bit(a, b)) for a, b in self.required_events],
                        dtype=np.int8)

    def get_required_events_reward(self):
        return sum(self.read_bit(a, b) for a, b in self.required_events)

    def _swarm_stages(self):
        """[(stage, path), ...] newest-progress-first."""
        out = []
        try:
            for f in self.swarm_dir.glob("stage_*.state"):
                try:
                    # `stage_7.state` and `stage_7_012.state` both read as stage 7. A ladder
                    # wants SEVERAL states per stage -- different points inside one segment are
                    # different practice, not duplicates -- so the trailing sequence number is
                    # deliberately allowed and ignored for ordering.
                    out.append((int(f.stem.split("_")[1]), f))
                except (IndexError, ValueError):
                    continue
        except OSError:
            pass
        return sorted(out, reverse=True)

    def _swarm_best(self):
        """(stage, path) of the furthest state any worker has published, or (0, None)."""
        st = self._swarm_stages()
        return st[0] if st else (0, None)

    def _swarm_publish(self, stage):
        """Publish this env's current emulator state as the new best.

        ⚠️ Written to a temp name and renamed: another worker may be reading this directory at
        the same instant, and a half-written save state would crash it on load rather than
        merely being ignored.
        """
        if not self.swarm_dir:
            return
        best, _ = self._swarm_best()
        if stage <= best:
            return
        try:
            tmp = self.swarm_dir / f".tmp_{uuid.uuid4().hex}.state"
            with open(tmp, "wb") as f:
                self.pyboy.save_state(f)
            os.replace(tmp, self.swarm_dir / f"stage_{stage}.state")
        except Exception:
            # 🚨 Deliberately broad. save_state raises PyBoyException, not OSError, and losing
            # one publish is nothing next to killing a worker 14 hours into an overnight run.
            try:
                tmp.unlink()
            except Exception:
                pass

    def _swarm_adopt(self):
        """Maybe start this episode from the swarm's furthest point instead of init.state.

        ⚠️ `swarm_p` is deliberately < 1. If every worker always adopted, all of them would
        sit in one identical state and the run would lose exactly the sample diversity that
        makes the gradient usable -- which is the failure this whole change exists to fix.
        The remaining share keeps starting from the beginning.
        """
        if not self.swarm_dir or self.np_random.random() >= self.swarm_p:
            self.swarm_loaded_stage = 0
            return False
        # 🔑 Pick an ORDER to try, then take the first that actually loads.
        #
        # Always taking the best is right for organic swarming (push the frontier) and wrong
        # for a demonstration ladder: every worker would teleport to the end and the middle of
        # the game would never be practised. So `swarm_frontier_p` of the time we take the
        # deepest state, and otherwise sample uniformly across the whole ladder. With only a
        # few stages -- early organic discovery -- uniform is already near the frontier, so a
        # single knob serves both cases without a mode flag.
        order = self._swarm_stages()                       # already sorted deepest-first
        if order and self.np_random.random() >= self.swarm_frontier_p:
            idx = list(self.np_random.permutation(len(order)))
            order = [order[i] for i in idx]

        # 🚨 A state file can be unreadable -- truncated by a crash mid-publish, or written by a
        # different PyBoy build ("Cannot load state from a newer version of PyBoy"). PyBoy
        # raises its own exception type, so this catches broadly on purpose: one bad file must
        # cost this episode's head start, never the worker. Falling through to init.state is
        # always a valid outcome.
        for stage, path in order:
            try:
                with open(path, "rb") as f:
                    self.pyboy.load_state(f)
                self.swarm_loaded_stage = stage
                return True
            except Exception:
                # Reload init.state: a failed load can leave the emulator half-written.
                try:
                    with open(self.init_state, "rb") as f:
                        self.pyboy.load_state(f)
                except Exception:
                    pass
                continue
        self.swarm_loaded_stage = 0
        return False

    def update_max_required_rew(self):
        # Ratchets, exactly like update_max_event_rew. Some of these flags are cleared by the
        # game after their scene ends (Bill's, the SS Anne's), and a reward that could go DOWN
        # would teach the agent to avoid finishing them.
        cur = max(self.get_required_events_reward() - self.base_required_flags, 0)
        if self.swarm_dir and cur > self.max_required_rew:
            # Publish the ABSOLUTE stage, not the baselined delta: a worker that adopted a
            # stage-8 state has a delta of 1 at stage 9, and naming the file by the delta
            # would overwrite stage 1 and make the swarm walk backwards.
            self._swarm_publish(int(self.swarm_loaded_stage + cur))
        self.max_required_rew = max(cur, self.max_required_rew)
        return self.max_required_rew

    def knows_cut(self):
        """True once any party member has CUT in a move slot. Addresses verified against a
        real save state (a L17 Charmeleon read back Scratch/Growl/Ember/Leer correctly).

        Generation-independent: Crystal gates Ilex Forest on Cut the same way, so only the
        move id and the party layout change."""
        return self.gspec.knows_move(self.read_m, self.gspec.cut_move_id)

    def update_max_cut_rew(self):
        self.max_cut_rew = max(int(self.knows_cut()), self.max_cut_rew)
        return self.max_cut_rew

    def get_game_state_reward(self, print_stats=False):
        # addresses from https://datacrystal.romhacking.net/wiki/Pok%C3%A9mon_Red/Blue:RAM_map
        # https://github.com/pret/pokered/blob/91dc3c9f9c8fd529bb6e8307b58b96efa0bec67e/constants/event_constants.asm
        # ⚠️ Weights below re-balance WITHIN events; they deliberately do NOT change the
        # event-vs-exploration balance, which at 160:1 per unit already matches published
        # practice (puffer runs ~246:1). The defect was that all events were equal.
        # Generic event 4 -> 1.5 and required at 15 keeps total event mass roughly constant
        # (103*4=412 before; 103*1.5 + 17*15 = 410 after), so this is a re-weighting rather
        # than a covert global rescale that would silently retune everything else too.
        state_scores = {
            "event": self.reward_scale * self.update_max_event_rew() * 1.5,
            "required": self.reward_scale * self.update_max_required_rew() * 15,
            "cut": self.reward_scale * self.update_max_cut_rew() * 50,
            #"level": self.reward_scale * self.get_levels_reward(),
            "heal": self.reward_scale * self.total_healing_rew * 10,
            #"op_lvl": self.reward_scale * self.update_max_op_level() * 0.2,
            #"dead": self.reward_scale * self.died_count * -0.1,
            "badge": self.reward_scale * self.get_badges() * 20,
            # Ratcheted (update_map_progress uses max()) and baselined, so it can only ever pay
            # for ground covered THIS episode, once.
            "map_progress": (self.reward_scale * self.map_weight
                             * max(self.max_map_progress - self.base_map_progress, 0)),
            "explore": self.reward_scale * self.explore_weight * len(self.seen_coords) * 0.1,
            # One interaction point is worth ~10 new tiles. Deliberately modest: Pleines et al.
            # found that scaling a navigation reward 10x STOPPED agents beating the first gym,
            # so this is sized to add density where there was none, not to dominate.
            "interact": (self.reward_scale * self.explore_weight
                         * len(self.seen_interactions) * self.interact_weight),
            "stuck": self.reward_scale * self.get_current_coord_count_reward() * -0.05
        }

        return state_scores

    def update_max_op_level(self):
        opp_base_level = 5
        opponent_level = self.gspec.opponent_level(self.read_m) - opp_base_level
        self.max_opponent_level = max(self.max_opponent_level, opponent_level)
        return self.max_opponent_level

    def update_max_event_rew(self):
        cur_rew = self.get_all_events_reward()
        self.max_event_rew = max(cur_rew, self.max_event_rew)
        return self.max_event_rew

    def update_heal_reward(self):
        cur_health = self.read_hp_fraction()
        # if health increased and party size did not change
        if (cur_health > self.last_health
                and self.gspec.party_count(self.read_m) == self.party_size):
            if self.last_health > 0:
                heal_amount = cur_health - self.last_health
                self.total_healing_rew += heal_amount * heal_amount
            else:
                self.died_count += 1

    def read_hp_fraction(self):
        return self.gspec.hp_fraction(self.read_m)

    def read_hp(self, start):
        return self.gspec.read_hp(self.read_m, start)

    # built-in since python 3.10
    def bit_count(self, bits):
        return bin(bits).count("1")
    
    def fourier_encode(self, val):
        return np.sin(val * 2 ** np.arange(self.enc_freqs))
    
    def update_map_progress(self):
        map_idx = self.gspec.map_id(self.read_m)
        self.max_map_progress = max(self.max_map_progress, self.get_map_progress(map_idx))
    
    def get_map_progress(self, map_idx):
        if map_idx in self.essential_map_locations.keys():
            return self.essential_map_locations[map_idx]
        else:
            return -1
