"""Per-game memory map and structural rules — the seam that lets one env serve two games.

Phase 1 of ~/.claude/plans/cozy-foraging-charm.md.

WHY
---
Everything Red-specific in red_gym_env_v2.py was a module literal or an inline hex address: ~40
of them, spread over 25 call sites, several duplicated (the six level addresses appear three
times, the party-count address four). A second game could only be supported by forking the file,
and a fork drifts — this project has already paid for that lesson three times (three `_disp`
helpers in the RPG, three "newest checkpoint" globs, two copies of the night-digest SQL).

🔑 THE ACCEPTANCE TEST IS BYTE-IDENTICAL BEHAVIOUR FOR RED, not a code review. Every method here
computes exactly what the literal it replaced computed, and tests/test_gamespec.py asserts that
against a real save state, address by address and observation array by observation array.

WHAT IS STRUCTURAL, NOT NUMERIC
-------------------------------
🚨 Two Gen 2 differences cannot be expressed as a different constant, which is why this is a
class hierarchy rather than a table of ints:

  1. **Map identity is a PAIR** in Gen 2 — (map_group, map_number) — where Gen 1 has one byte.
     Every coordinate key, the explore map, and map progress all flow from it.
  2. **Badges span TWO bytes** (Johto + Kanto), so the badge count, the badge observation and
     its width all change shape.

`Gen1Spec` and `Gen2Spec` differ in exactly those methods and nothing else.

WHERE THIS FILE LIVES, AND WHY IT IS NOT AT THE REPO ROOT
---------------------------------------------------------
⚠️ It must sit in `v2/`, beside red_gym_env_v2.py and global_map.py. train_worker.py finds the
env on the PC by WALKING for a directory named `v2` containing red_gym_env_v2.py — precisely
because the PC's checkout may be a GitHub ZIP nested as
`PokemonRedExperiments-master/PokemonRedExperiments-master/v2`, a tree that contains no gamereg.py
and no repo root at all. A spec module at the repo root would import fine on this box and fail on
the training PC, and we would not find out until an overnight run died.

⚠️ Crystal's env will live in repo-crystal/v2/ and needs this same module. That is a PHASE 2
decision (symlink, or a path insert) and is deliberately not pre-empted here — but do NOT
"tidy" it by moving this file up a level. Read the paragraph above first.
"""
import numpy as np


class World:
    """How local (map, x, y) coordinates become a position on the visited-map canvas."""

    shape = (0, 0)

    def to_global(self, r, c, map_n):
        raise NotImplementedError


class StitchedWorld(World):
    """One canvas for the entire game, with every map hand-placed on it (Gen 1).

    Delegates to global_map.py, which loads map_data.json's 226 hand-stitched Kanto regions.
    Deliberately a pass-through and not a reimplementation: byte-identical output is then true
    by construction rather than by test.
    """

    def __init__(self):
        from global_map import local_to_global, GLOBAL_MAP_SHAPE
        self._to_global = local_to_global
        self.shape = GLOBAL_MAP_SHAPE

    def to_global(self, r, c, map_n):
        return self._to_global(r, c, map_n)


class TiledWorld(World):
    """A small canvas PER MAP, tiled into a grid — for a game with no stitched atlas.

    🔑 Gen 2 spans Johto AND Kanto and pret/pokecrystal ships no equivalent of map_data.json's
    placements, so building a stitched atlas up front is weeks of work for a benefit the mask
    does not need: the visited map answers "have I stood here before", which is per-map. Global
    spatial continuity is an optimisation, not a requirement, and an atlas computed from
    maps/map_headers.asm can replace this later without touching the env.

    🔑 REGION TRAVEL IS A NON-ISSUE HERE, BY CONSTRUCTION. Johto and Kanto maps live in
    different map groups, `Gen2Spec.map_id` packs the group into the id, and every map gets its
    own cell — so sailing Olivine -> Vermilion is just another map id, exactly like walking
    through a door. There is no seam to cross and no coordinate system to reconcile.

    ⚠️ Slots are assigned in first-seen order, so the canvas is NOT stable across episodes — map
    7 may land in a different cell next run. That is fine for a per-episode visited mask (which
    resets anyway) and would NOT be fine for anything comparing two runs' maps pixel-to-pixel.

    🚨 SIZE IT FROM THE REAL MAP COUNT. The first version defaulted to a 16x16 grid = 256 slots,
    and pret/pokecrystal's constants/map_constants.asm defines 26 map groups totalling ~330
    maps — so roughly 74 of them would have silently shared a cell with another map, merging two
    places in the visited mask with no error anywhere. Default is now 400 and overflow WARNS.

    ⚠️ `cell` must be at least as large as the biggest map's tile dimensions or coordinates wrap
    within a single map, which is the same silent merge one level down. 72x72 tiles is a guess
    that covers ordinary routes and towns. Phase 2 should compute both `n_maps` and `cell` from
    map_constants.asm, which carries each map's width and height in blocks (1 block = 2 tiles)
    right next to the id we already have to parse.
    """

    def __init__(self, n_maps=400, cell=(72, 72), pad=20):
        import math
        self.cell = cell
        self.pad = pad
        cols = max(1, math.ceil(math.sqrt(n_maps)))
        rows = max(1, math.ceil(n_maps / cols))
        self.grid = (rows, cols)
        self.slots = rows * cols
        self._slot = {}
        self._warned = False
        self.shape = (cell[0] * rows + pad * 2, cell[1] * cols + pad * 2)

    def to_global(self, r, c, map_n):
        s = self._slot.get(map_n)
        if s is None:
            if len(self._slot) >= self.slots and not self._warned:
                # Loud, once. A silent wrap merges two real places in the visited mask and
                # looks like the agent revisiting somewhere it has never been.
                self._warned = True
                print(f"TiledWorld: more than {self.slots} maps seen — cells are now being "
                      f"reused and distinct maps will collide. Raise n_maps.", flush=True)
            s = self._slot[map_n] = len(self._slot) % self.slots
        gy = (s // self.grid[1]) * self.cell[0] + (r % self.cell[0]) + self.pad
        gx = (s % self.grid[1]) * self.cell[1] + (c % self.cell[1]) + self.pad
        return gy, gx


class GameSpec:
    """One game's RAM layout, content files and structural rules.

    Methods take a `read_m(addr) -> int` callable rather than holding the emulator, so a spec is
    a plain value: constructible in a test, comparable, and impossible to accidentally bind to
    the wrong PyBoy instance.
    """

    slug = "?"
    # ── party ────────────────────────────────────────────────────────────────────────────
    party_count_addr = 0
    party_struct_addr = 0
    party_struct_size = 0
    party_moves_offset = 0
    party_species_addrs = ()
    level_addrs = ()
    hp_addrs = ()
    max_hp_addrs = ()
    opponent_level_addrs = ()
    # ── world position ───────────────────────────────────────────────────────────────────
    x_addr = 0
    y_addr = 0
    map_addr = 0
    map_group_addr = None            # Gen 2 only
    # ── flags ────────────────────────────────────────────────────────────────────────────
    badges_addr = 0
    badge_bytes = 1
    in_battle_addr = 0
    event_flags_start = 0
    event_flags_end = 0
    # (addr, bit) pairs excluded from the generic event popcount — Gen 1's museum ticket is
    # set at the start of the game and is not progress.
    excluded_event_flags = ()
    # ── content ──────────────────────────────────────────────────────────────────────────
    cut_move_id = 0
    events_file = "events.json"
    required_events_file = "required_events.json"
    essential_maps = ()              # ordered: index in this tuple IS the progress score
    world_factory = StitchedWorld

    # ── derived ──────────────────────────────────────────────────────────────────────────
    @property
    def n_badge_bits(self):
        return self.badge_bytes * 8

    @property
    def n_event_bits(self):
        return (self.event_flags_end - self.event_flags_start) * 8

    @property
    def map_progress(self):
        """map id -> rank along the critical path. -1 for anything not on it."""
        return {v: i for i, v in enumerate(self.essential_maps)}

    def world(self):
        return self.world_factory()

    # ── reads: shared across generations ─────────────────────────────────────────────────
    def levels(self, read_m):
        return [read_m(a) for a in self.level_addrs]

    def party_species(self, read_m):
        return [read_m(a) for a in self.party_species_addrs]

    def party_count(self, read_m):
        return read_m(self.party_count_addr)

    def in_battle(self, read_m):
        return read_m(self.in_battle_addr) != 0

    def read_hp(self, read_m, start):
        return 256 * read_m(start) + read_m(start + 1)

    def hp_fraction(self, read_m):
        hp = sum(self.read_hp(read_m, a) for a in self.hp_addrs)
        mx = max(sum(self.read_hp(read_m, a) for a in self.max_hp_addrs), 1)
        return hp / mx

    def opponent_level(self, read_m):
        return max(read_m(a) for a in self.opponent_level_addrs)

    def knows_move(self, read_m, move_id):
        """True once any party member has `move_id` in a move slot.

        🔑 Holding the HM item is not the gate — the obstacle only opens once the move is
        TAUGHT. Rewarding the item stops one step short of the thing that actually unblocks
        progress. This is generation-independent: Crystal gates Ilex Forest on Cut the same way.
        """
        n = self.party_count(read_m)
        for i in range(min(n, 6)):
            base = self.party_struct_addr + self.party_struct_size * i
            for j in range(4):
                if read_m(base + self.party_moves_offset + j) == move_id:
                    return True
        return False

    def event_popcount(self, read_m):
        return sum(bin(read_m(i)).count("1")
                   for i in range(self.event_flags_start, self.event_flags_end))

    def event_bits(self, read_m):
        return [int(b) for i in range(self.event_flags_start, self.event_flags_end)
                for b in f"{read_m(i):08b}"]

    def excluded_event_count(self, read_m):
        return sum(int(bin(256 + read_m(a))[-b - 1] == "1")
                   for a, b in self.excluded_event_flags)

    # ── structural: overridden per generation ────────────────────────────────────────────
    def coords(self, read_m):
        """(x, y, map_id). map_id must be hashable and unique per map."""
        raise NotImplementedError

    def map_id(self, read_m):
        raise NotImplementedError

    def badge_count(self, read_m):
        raise NotImplementedError

    def badge_bits(self, read_m):
        raise NotImplementedError


class Gen1Spec(GameSpec):
    """Red/Blue/Yellow: one map byte, one badge byte."""

    def coords(self, read_m):
        return (read_m(self.x_addr), read_m(self.y_addr), read_m(self.map_addr))

    def map_id(self, read_m):
        return read_m(self.map_addr)

    def badge_count(self, read_m):
        return bin(read_m(self.badges_addr)).count("1")

    def badge_bits(self, read_m):
        # MSB-first per byte, matching the original f"{v:08b}" expression exactly.
        return np.array([int(b) for b in f"{read_m(self.badges_addr):08b}"], dtype=np.int8)


class Gen2Spec(GameSpec):
    """Gold/Silver/Crystal: map identity is (group, number); badges span two bytes.

    ⚠️ NO CRYSTAL ADDRESSES ARE DECLARED HERE. Deriving them from pret/pokecrystal's symbol
    table — and verifying each against two real save states — is Phase 2. This class exists so
    the structural code paths are written and TESTED (tests/test_gamespec.py drives it with
    synthetic memory) rather than being written for the first time against a live ROM.
    """

    badge_bytes = 2

    def map_id(self, read_m):
        # Packed into one int so it stays hashable and usable as a dict key, exactly like Gen 1's
        # single byte. The map "number" is not unique on its own — group 1 map 3 and group 2
        # map 3 are different places — so a naive port that read only the number would silently
        # merge maps and quietly corrupt both the coord set and the explore map.
        return (read_m(self.map_group_addr) << 8) | read_m(self.map_addr)

    def coords(self, read_m):
        return (read_m(self.x_addr), read_m(self.y_addr), self.map_id(read_m))

    def badge_count(self, read_m):
        return sum(bin(read_m(self.badges_addr + i)).count("1")
                   for i in range(self.badge_bytes))

    def badge_bits(self, read_m):
        return np.array([int(b) for i in range(self.badge_bytes)
                         for b in f"{read_m(self.badges_addr + i):08b}"], dtype=np.int8)


class RedSpec(Gen1Spec):
    """Pokemon Red.

    Addresses from https://datacrystal.romhacking.net/wiki/Pok%C3%A9mon_Red/Blue:RAM_map and
    https://github.com/pret/pokered — carried over UNCHANGED from the literals they replaced.
    Every one is asserted equal to its original value in tests/test_gamespec.py, so a typo here
    is a test failure rather than a subtly wrong reward.
    """

    slug = "red"

    party_count_addr = 0xD163            # wPartyCount
    party_struct_addr = 0xD16B           # wPartyMon1
    party_struct_size = 44
    party_moves_offset = 8               # moves at +8..+11
    party_species_addrs = (0xD164, 0xD165, 0xD166, 0xD167, 0xD168, 0xD169)
    level_addrs = (0xD18C, 0xD1B8, 0xD1E4, 0xD210, 0xD23C, 0xD268)
    hp_addrs = (0xD16C, 0xD198, 0xD1C4, 0xD1F0, 0xD21C, 0xD248)
    max_hp_addrs = (0xD18D, 0xD1B9, 0xD1E5, 0xD211, 0xD23D, 0xD269)
    opponent_level_addrs = (0xD8C5, 0xD8F1, 0xD91D, 0xD949, 0xD975, 0xD9A1)

    x_addr = 0xD362
    y_addr = 0xD361
    map_addr = 0xD35E

    badges_addr = 0xD356
    badge_bytes = 1
    in_battle_addr = 0xD057
    event_flags_start = 0xD747
    event_flags_end = 0xD87E             # expanded for SS Anne; was 0xD7F6
    excluded_event_flags = ((0xD754, 0),)   # museum ticket

    cut_move_id = 15
    # Ordered critical path; the index IS the progress rank, and max_map_progress ratchets over it.
    #
    # 🚨 EXTENDED 2026-09-02, and the extension is load-bearing rather than cosmetic. The original
    # 15 stopped at Cerulean Gym, which the agent now clears routinely — measured over 16 real
    # evaluation runs, EVERY run that got past Brock scored exactly 14/14, including the two that
    # went on to take HM01 and leave the S.S. Anne. The table was completely flat across the whole
    # interesting region, so a reward built on it would have paid densely for the early game
    # (which published results already clear 85-99% of the time) and nothing at all at the
    # frontier. Re-measured with the extension: those same runs score 22-23 of 24 and it separates
    # stage-14 from stage-16 runs. Shallow runs are unchanged.
    #
    # The continuation mirrors the required-event chain: the Bill branch (ticket) before Vermilion,
    # because you cannot board without it, then the ship, then gym 3 behind the cuttable tree.
    essential_maps = (
        40, 0, 12, 1, 13, 51, 2, 54, 14, 59, 60, 61, 15, 3, 65,   # Oak's Lab -> Cerulean Gym
        35, 36, 88,                                                # Route 24/25 -> Bill's Lab
        16, 17, 5,                                                 # Route 5/6 -> Vermilion City
        94, 95, 101,                                               # Harbor -> S.S. Anne -> captain
        92,                                                        # Vermilion Gym (behind Cut)
    )
    world_factory = StitchedWorld


SPECS = {"red": RedSpec}


def get(slug):
    """Resolve a slug to a spec INSTANCE, or raise naming the valid set.

    Deliberately no default: a typo'd slug that silently returned Red's spec would train a
    second game against the wrong RAM map and look like a bad reward function for weeks.
    """
    try:
        return SPECS[slug]()
    except KeyError:
        raise KeyError(f"unknown game spec {slug!r}; known: {sorted(SPECS)}")
