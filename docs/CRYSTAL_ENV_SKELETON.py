Below is a fail-closed draft. **Every memory location is a named, nonnumeric sentinel. Reading one raises before accessing the emulator.** No candidate addresses are used.

The filesystem runner failed, so this is an inline draft, not a saved or tested file. The supplied Red excerpt also stops before its reward implementation; the rewards below are explicit design choices, not a claim of exact parity.

Crystal-specific decisions:

- **Badges:** concatenate Johto’s eight bits and Kanto’s eight bits, in that order.
- **Maps:** retain `(group, number)` everywhere. Count places with those pairs and tiles with `(group, number, x, y)`. Use a map-local exploration image until Crystal has its own map atlas.
- **Events:** Crystal’s source defines **2,048 bits / 256 bytes**. Decode least-significant bit first. Required milestones use symbolic event names resolved to bit indices, never address strings. Generic flags include object visibility and other state, so raw popcount is not a reliable progress measure. [Event definitions](https://github.com/pret/pokecrystal/blob/master/constants/event_flags.asm)
- **Party:** read only occupied slots; exclude eggs from health and level shaping. Crystal’s party structure includes held items, happiness and separate Special Attack/Defense. Red’s offsets and stored type assumptions do not carry over. Party field labels are macro-generated; their absence as literal declarations does **not** mean they cannot appear in a symbol file. [Structure macros](https://github.com/pret/pokecrystal/blob/master/macros/ram.asm)
- **Battle:** use Crystal’s battle-mode semantics, not a transplanted Red predicate. Banked WRAM requires bank information from the matching symbol file. [WRAM declarations](https://github.com/pret/pokecrystal/blob/master/ram/wram.asm)
- **Other changes:** do not reuse Red’s dialogue brightness threshold on Crystal’s color screen, its Cut milestone, or its progression ranks. Fix RTC behavior for reproducible training; emulator save-state/RTC behavior must be checked with the chosen PyBoy version.

```python
from collections import deque
from dataclasses import dataclass
from typing import Final

import gymnasium as gym
from gymnasium import spaces
import numpy as np


class UnresolvedMemoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissingAddress:
    symbol: str

    def fail(self):
        raise UnresolvedMemoryError(
            f"{self.symbol}: Crystal memory location is unresolved. "
            "Require a ROM-matched symbol file, WRAM bank, and "
            "live-state validation before enabling this read."
        )

    def __int__(self):
        self.fail()

    def __index__(self):
        self.fail()


# These are dimensions/counts, never memory locations.
EVENT_BITS: Final = 2048
EVENT_BYTES: Final = EVENT_BITS // 8
PARTY_CAPACITY: Final = 6

# All memory locations remain sentinels.
MAP_GROUP: Final = MissingAddress("wMapGroup")
MAP_NUMBER: Final = MissingAddress("wMapNumber")
PLAYER_X: Final = MissingAddress("wXCoord")
PLAYER_Y: Final = MissingAddress("wYCoord")
BATTLE_MODE: Final = MissingAddress("wBattleMode")
JOHTO_BADGES: Final = MissingAddress("wJohtoBadges")
KANTO_BADGES: Final = MissingAddress("wKantoBadges")
EVENT_FLAGS: Final = MissingAddress("wEventFlags")
PARTY_COUNT: Final = MissingAddress("wPartyCount")
PARTY_SPECIES: Final = MissingAddress("wPartySpecies")

# Resolve each generated field independently; no guessed base or stride.
PARTY_LEVEL: Final = tuple(
    MissingAddress(f"wPartyMon{i}Level")
    for i in range(1, PARTY_CAPACITY + 1)
)
PARTY_HP: Final = tuple(
    MissingAddress(f"wPartyMon{i}HP")
    for i in range(1, PARTY_CAPACITY + 1)
)
PARTY_MAX_HP: Final = tuple(
    MissingAddress(f"wPartyMon{i}MaxHP")
    for i in range(1, PARTY_CAPACITY + 1)
)

ALL_ADDRESSES: Final = (
    MAP_GROUP, MAP_NUMBER, PLAYER_X, PLAYER_Y, BATTLE_MODE,
    JOHTO_BADGES, KANTO_BADGES, EVENT_FLAGS,
    PARTY_COUNT, PARTY_SPECIES,
    *PARTY_LEVEL, *PARTY_HP, *PARTY_MAX_HP,
)


class CrystalRAM:
    """Replace only after symbol binding and live-state validation."""

    def require_resolved(self):
        raise UnresolvedMemoryError(
            "Unresolved Crystal symbols: "
            + ", ".join(a.symbol for a in ALL_ADDRESSES)
        )

    def read(self, address, width):
        # Deliberately no emulator-memory fallback.
        address.fail()

    def u8(self, address):
        return self.read(address, 1)[0]

    def u16be(self, address):
        return int.from_bytes(self.read(address, 2), "big")

    @staticmethod
    def bits(raw):
        return np.unpackbits(
            np.asarray(raw, dtype=np.uint8), bitorder="little"
        ).astype(np.int8)

    def snapshot(self, egg_species):
        count = self.u8(PARTY_COUNT)
        if not 0 <= count <= PARTY_CAPACITY:
            raise ValueError("Invalid Crystal party count")

        species = self.read(PARTY_SPECIES, PARTY_CAPACITY)
        levels, hp, max_hp = [], [], []
        for i in range(count):
            if species[i] == egg_species:
                continue
            level = self.u8(PARTY_LEVEL[i])
            current = self.u16be(PARTY_HP[i])
            maximum = self.u16be(PARTY_MAX_HP[i])
            if not (1 <= level <= 100 and 0 <= current <= maximum
                    and maximum > 0):
                raise ValueError("Invalid Crystal party fields")
            levels.append(level)
            hp.append(current)
            max_hp.append(maximum)

        mode = self.u8(BATTLE_MODE)
        if mode not in (0, 1, 2):
            raise ValueError("Invalid Crystal battle mode")

        return {
            "map_id": (self.u8(MAP_GROUP), self.u8(MAP_NUMBER)),
            "x": self.u8(PLAYER_X),
            "y": self.u8(PLAYER_Y),
            "battle": mode != 0,
            # Empty party is legitimate before receiving a starter.
            "health": sum(hp) / sum(max_hp) if max_hp else 0.0,
            "level_sum": sum(levels),
            "badges": self.bits([
                self.u8(JOHTO_BADGES), self.u8(KANTO_BADGES)
            ]),
            "events": self.bits(self.read(EVENT_FLAGS, EVENT_BYTES)),
        }


class CrystalGymEnv(gym.Env):
    """
    backend contract:
      load_initial_state(): restore Crystal state and controlled RTC
      release_all(): release every supported button
      act(button, frames, hold_frames): press, tick, release, tick;
                                       render the final frame
      rgb(): return the current RGB screen
      close(): release emulator resources

    Backend creation is deferred until reset passes memory validation.
    """
    metadata = {"render_modes": ["rgb_array"]}
    BUTTONS = ("down", "left", "right", "up", "a", "b", "start")

    def __init__(
        self, backend_factory, *,
        egg_species, required_event_indices, progress_event_indices,
        map_ranks, action_freq=24, max_steps=163840,
        reward_scale=1.0, weights=None,
    ):
        super().__init__()
        self.ram = CrystalRAM()  # No unverified numeric injection seam.
        self.backend_factory = backend_factory
        self.backend = None
        self.egg_species = egg_species  # Matching source's EGG constant.
        self.required = self._indices(required_event_indices)
        self.generic = self._indices(progress_event_indices)

        if set(self.required) & set(self.generic):
            raise ValueError("Required and generic event sets must be disjoint")
        if action_freq < 8 or max_steps < 1:
            raise ValueError("Invalid action frequency or episode length")
        if any(
            not isinstance(key, tuple) or len(key) != 2 or rank < 0
            for key, rank in map_ranks.items()
        ):
            raise ValueError("Map ranks require (group, number) keys")

        self.map_ranks = dict(map_ranks)
        self.action_freq = action_freq
        self.max_steps = max_steps
        self.reward_scale = reward_scale
        # Provisional coefficients, not Crystal-calibrated results.
        self.weights = {
            "event": 1.0, "required": 10.0, "badge": 20.0,
            "explore": 0.1, "level": 1.0, "map": 4.0,
        }
        if weights is not None:
            if set(weights) - set(self.weights):
                raise ValueError("Unknown reward term")
            self.weights.update(weights)

        self.action_space = spaces.Discrete(len(self.BUTTONS))
        obs = {
            "screens": spaces.Box(0, 255, (72, 80, 3), np.uint8),
            "health": spaces.Box(0, 1, (1,), np.float32),
            "level": spaces.Box(-1, 1, (8,), np.float32),
            "badges": spaces.MultiBinary(16),
            "events": spaces.MultiBinary(EVENT_BITS),
            "map": spaces.Box(0, 255, (48, 48, 1), np.uint8),
            "recent_actions": spaces.MultiDiscrete([7, 7, 7]),
        }
        if len(self.required):
            obs["required_events"] = spaces.MultiBinary(len(self.required))
        self.observation_space = spaces.Dict(obs)
        self.active = False

    @staticmethod
    def _indices(values):
        values = tuple(values)
        if any(not isinstance(v, int) or not 0 <= v < EVENT_BITS
               for v in values):
            raise ValueError("Event indices must come from Crystal constants")
        if len(set(values)) != len(values):
            raise ValueError("Duplicate event indices")
        return list(values)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.active = False

        # Fails before backend creation, state loading, or any training action.
        self.ram.require_resolved()

        if self.backend is None:
            self.backend = self.backend_factory()
        self.backend.load_initial_state()
        self.backend.release_all()
        # Any future swarm adoption belongs here, before the snapshot.
        self.state = self.ram.snapshot(self.egg_species)

        self.steps = 0
        self.stats = deque(maxlen=256)
        self.tiles, self.places = set(), set()
        self.screens = np.zeros((72, 80, 3), dtype=np.uint8)
        self.actions = np.zeros(3, dtype=np.int64)
        self.latched_events = self.state["events"].copy()
        self.latched_badges = self.state["badges"].copy()
        self.best_level = self.state["level_sum"]
        self.best_rank = self.map_ranks.get(self.state["map_id"], 0)

        self._visit(self.state)
        self.previous_terms = self._potential()
        self._push_screen()
        self.active = True
        return self._get_obs(), self._info()

    def step(self, action):
        if not self.active:
            raise RuntimeError("Call reset successfully before step")
        if not self.action_space.contains(action):
            raise ValueError("Invalid action")

        self.backend.act(self.BUTTONS[int(action)], self.action_freq, 8)
        self.state = self.ram.snapshot(self.egg_species)
        self.steps += 1

        self.actions[1:] = self.actions[:-1].copy()
        self.actions[0] = action
        self._visit(self.state)
        self.latched_events |= self.state["events"]
        self.latched_badges |= self.state["badges"]
        self.best_level = max(self.best_level, self.state["level_sum"])
        if not self.state["battle"]:
            self.best_rank = max(
                self.best_rank,
                self.map_ranks.get(self.state["map_id"], 0),
            )

        terms = self._potential()
        deltas = {
            k: self.reward_scale * (terms[k] - self.previous_terms[k])
            for k in terms
        }
        self.previous_terms = terms
        self._push_screen()

        # No invented "game completed" RAM predicate.
        terminated = False
        truncated = self.steps >= self.max_steps
        self.active = not (terminated or truncated)
        info = self._info()
        info["reward_terms"] = deltas
        self.stats.append(info.copy())
        return (
            self._get_obs(), float(sum(deltas.values())),
            terminated, truncated, info,
        )

    def _visit(self, state):
        if not state["battle"]:
            group, number = state["map_id"]
            self.places.add((group, number))
            self.tiles.add((group, number, state["x"], state["y"]))

    def _potential(self):
        counts = {
            "event": int(self.latched_events[self.generic].sum()),
            "required": int(self.latched_events[self.required].sum()),
            "badge": int(self.latched_badges.sum()),
            "explore": len(self.tiles),
            "level": self.best_level / 100.0,
            "map": self.best_rank,
        }
        return {k: self.weights[k] * v for k, v in counts.items()}

    def _local_map(self):
        group, number = self.state["map_id"]
        x, y = self.state["x"], self.state["y"]
        patch = np.zeros((24, 24), dtype=np.uint8)
        for row in range(24):
            for col in range(24):
                key = (group, number, x + col - 12, y + row - 12)
                patch[row, col] = 255 if key in self.tiles else 0
        return patch.repeat(2, axis=0).repeat(2, axis=1)[..., None]

    def _push_screen(self):
        rgb = np.asarray(self.backend.rgb())
        if rgb.shape != (144, 160, 3):
            raise ValueError("Unexpected emulator screen shape")
        gray = rgb.astype(np.float32).mean(axis=2)
        small = gray.reshape(72, 2, 80, 2).mean(axis=(1, 3))
        self.screens[:, :, 1:] = self.screens[:, :, :-1].copy()
        self.screens[:, :, 0] = small.astype(np.uint8)

    def _get_obs(self):
        # This method does not advance the frame stack.
        phase = 0.02 * self.state["level_sum"] * (2.0 ** np.arange(8))
        obs = {
            "screens": self.screens.copy(),
            "health": np.array([self.state["health"]], dtype=np.float32),
            "level": np.sin(phase).astype(np.float32),
            "badges": self.state["badges"].copy(),
            "events": self.state["events"].copy(),
            "map": self._local_map(),
            "recent_actions": self.actions.copy(),
        }
        if len(self.required):
            obs["required_events"] = self.state["events"][self.required].copy()
        return obs

    def _info(self):
        return {
            "step": self.steps,
            "map_id": self.state["map_id"],
            "places_visited": len(self.places),
            "tiles_visited": len(self.tiles),
        }

    def render(self):
        if self.backend is None:
            raise RuntimeError("Emulator has not been initialized")
        return np.asarray(self.backend.rgb()).copy()

    def close(self):
        self.active = False
        if self.backend is not None:
            self.backend.close()
            self.backend = None
```

**Complete memory manifest for this draft:** each row needs the symbol’s bank and location from the matching build. Array widths below are byte counts, not locations.

| Named sentinel | Symbol(s) to resolve | Byte width | Purpose |
|---|---|---:|---|
| `MAP_GROUP` | `wMapGroup` | 1 | First component of map identity |
| `MAP_NUMBER` | `wMapNumber` | 1 | Second component of map identity |
| `PLAYER_X` | `wXCoord` | 1 | Player tile column |
| `PLAYER_Y` | `wYCoord` | 1 | Player tile row |
| `BATTLE_MODE` | `wBattleMode` | 1 | Suppress battle exploration and map progress |
| `JOHTO_BADGES` | `wJohtoBadges` | 1 | Eight Johto badge flags |
| `KANTO_BADGES` | `wKantoBadges` | 1 | Eight Kanto badge flags |
| `EVENT_FLAGS` | `wEventFlags` | 256 | Event observation and curated milestones |
| `PARTY_COUNT` | `wPartyCount` | 1 | Occupied party slots |
| `PARTY_SPECIES` | `wPartySpecies` | 6 | Identify eggs in occupied slots; excludes trailing terminator |
| `PARTY_LEVEL[0..5]` | `wPartyMon1Level` … `wPartyMon6Level` | 1 each | Non-egg party levels |
| `PARTY_HP[0..5]` | `wPartyMon1HP` … `wPartyMon6HP` | 2 each, big-endian | Current HP |
| `PARTY_MAX_HP[0..5]` | `wPartyMon1MaxHP` … `wPartyMon6MaxHP` | 2 each, big-endian | Maximum HP |

Required-event observations reuse `EVENT_FLAGS`; screens come from the emulator API. There are no hidden dialogue, inventory, opponent, completion, or global-map reads.

Reward behavior is deliberately explicit:

| Term | Progress credited |
|---|---|
| Generic events | First observed set of each **curated** progress flag |
| Required events | First observed set of each Crystal critical-path flag |
| Badges | Newly observed Johto or Kanto badge |
| Exploration | Newly visited `(group, number, x, y)` |
| Levels | Increase in highest observed non-egg party level sum |
| Map progress | Increase in a Crystal-specific, pair-keyed rank |

Every term is baselined after loading the initial state. Event latches prevent clearing and resetting a flag from repeatedly earning reward. Level-sum shaping remains susceptible to party acquisition/composition effects; it is a bounded training heuristic, not measured experience gain.

Healing and interaction rewards are disabled pending Crystal-specific validation. An HP-fraction increase alone can mean a party change rather than healing. Cut acquisition, learning Cut, and permission to use it must be distinguished if that milestone is added.

To activate this draft, bind all manifest entries in one symbol-file pass, retain WRAM banks, verify the built binary matches the project ROM, and validate known party/map/badge values and transitions in-game. Then implement the backend contract and replace the intentionally blocked reader. Range checks alone cannot establish correctness: plausible noise passes them.
