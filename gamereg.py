#!/usr/bin/env python3
"""The game registry — one place that knows which Pokemon game is which, and where its files
live. Phase 0 of ~/.claude/plans/cozy-foraging-charm.md.

WHY THIS EXISTS
---------------
🚨 Three separate places independently implemented "the current checkpoint is the newest file in
one directory": nightly.py's `max(glob("runs/*.zip"), key=mtime)`, promote.py's copy+utime, and
the volley server's /api/train/base. They agree only by coincidence, and they all break the
moment runs/ holds two games — promoting Crystal would silently become what Red's broadcast
loads. `current_checkpoint()` below is meant to be the ONLY implementation. This is the same
"N hand-rolled copies drift" failure as the three _disp helpers in the RPG.

🚨 A second game's policy can never share a directory with Red's. Crystal has 16 badges (2 bytes)
where Red has 8 (1 byte), a different event-flag range and a different map canvas — all three are
OBSERVATION SPACE differences, so the checkpoints are structurally unloadable against each
other's env. We hit "Observation spaces do not match" twice in one week with a single game and
two obs shapes; it cost a whole overnight eval. Namespacing is what stops that becoming
permanent and silent.

Checkpoint filenames make it worse: train_worker.py emits `poke_{steps}_steps.zip` with no game
id, and step counts restart at 0 every run — so two games' `poke_1000000_steps.zip` would collide
in one directory and the upload endpoint's os.replace() would silently overwrite. Collision is
the DEFAULT here, not an edge case.

⚠️ MIGRATION IS DELIBERATELY NOT DONE YET. `red` still resolves to its historical flat
`candidates/` and `repo/v2/runs/` because a 9-hour eval and an 8-hour training run were both live
when this landed, and both hold paths they globbed at start. `_dir()` prefers the namespaced
`<base>/<slug>/` and falls back to the flat legacy path only for `red`. Once the flat dirs are
moved into `candidates/red/` and `runs/red/`, the fallback simply stops being taken — no code
change needed, and nothing breaks in either order.
"""
import glob
import hashlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))


class Game:
    def __init__(self, slug, label, repo, rom, init_state, env_module, badges,
                 chzzk_id=None, env_class="RedGymEnv", rom_sha1=None):
        self.slug = slug
        self.label = label
        self.repo = repo                      # holds the ROM and init.state
        self.v2 = os.path.join(repo, "v2")    # env module + runs/
        self.rom = rom
        self.rom_sha1 = rom_sha1              # see verify_rom()
        self.init_state = init_state
        self.env_module = env_module
        self.env_class = env_class
        self.badges = badges                  # 8 for Gen 1, 16 for Gen 2 — the overlay reads this
        self.chzzk_id = chzzk_id

    def available(self):
        """True when this game's ROM and env module are actually present. Crystal is declared
        before it is usable on purpose, so the plumbing can be built and tested without one."""
        return (os.path.isfile(os.path.join(self.repo, self.rom))
                and os.path.isfile(os.path.join(self.v2, self.env_module + ".py")))

    def rom_path(self):
        return os.path.join(self.repo, self.rom)

    def verify_rom(self, path=None):
        """(ok, detail) — is the ROM the one every score in this project was measured against?

        🔑 Nothing in this pipeline checked this until 2026-09-05. `available()` and
        train_worker's --check test for a file's EXISTENCE, and the expected hash lived only in
        prose in three README files. That was tolerable while one person supplied the ROM by
        hand; it is not once contributors supply their own, because a different revision or a
        truncated copy produces scores that look perfectly ordinary and are measuring a
        different game. Fail loudly at startup instead.
        """
        p = path or self.rom_path()
        if not os.path.isfile(p):
            return False, f"no ROM at {p}"
        if not self.rom_sha1:
            return True, "no reference hash recorded for this game — not verified"
        h = hashlib.sha1()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        got = h.hexdigest()
        if got != self.rom_sha1:
            return False, f"ROM sha1 {got} != expected {self.rom_sha1}"
        return True, got

    def __repr__(self):
        return f"<Game {self.slug} badges={self.badges} available={self.available()}>"


GAMES = {
    "red": Game(
        slug="red", label="Pokemon Red",
        repo=os.path.join(HERE, "repo"),
        rom="PokemonRed.gb", init_state="init.state",
        # Pokemon Red (UE) [S][!]. Every score in eval_results.json was measured against this
        # exact file; a contributor running a different revision is not playing the same game.
        rom_sha1="ea9bcae617fdf159b045185467ae58b2e4a48b9a",
        env_module="red_gym_env_v2", badges=8,
        chzzk_id="Pokemon_Red",
    ),
    # Declared, not yet usable — available() is False until a ROM and env module exist.
    # ⚠️ Do NOT point this at repo/ : Crystal needs its own repo root, because the env's paths
    # ('../PokemonRed.gb', '../init.state') are relative to the v2 dir the caller chdir's into.
    "crystal": Game(
        slug="crystal", label="Pokemon Crystal",
        repo=os.path.join(HERE, "repo-crystal"),
        rom="PokemonCrystal.gbc", init_state="init.state",
        rom_sha1="f2f52230b536214ef7c9924f483392993e226cfb",   # see docs/GEN2.md
        env_module="crystal_gym_env", env_class="CrystalGymEnv", badges=16,
        chzzk_id=None,                        # ⚠️ must be resolved by ENUMERATION, never guessed:
                                              # CHZZK's fuzzy search returns 포켓몬 포코피아 for
                                              # "포켓몬", and Twitch returns Scarlet/Violet for
                                              # "Pokemon". Verified ids only.
    ),
}

DEFAULT_SLUG = "red"


def get(slug):
    """Resolve a slug, or raise with the valid set. Callers that take a slug from a request MUST
    go through this — an unknown slug has to fail loudly, never fall through to a default, or an
    upload lands in the wrong game's directory."""
    try:
        return GAMES[slug]
    except KeyError:
        raise KeyError(f"unknown game {slug!r}; known: {sorted(GAMES)}")


def _dir(base, slug, legacy):
    """Namespaced path if it exists, else the legacy flat path (red only, pre-migration)."""
    ns = os.path.join(base, slug)
    if os.path.isdir(ns):
        return ns
    if slug == DEFAULT_SLUG and os.path.isdir(legacy):
        return legacy
    return ns                                  # new game: return the namespaced path to create


def cand_dir(slug):
    """Where the training worker's uploads land, awaiting evaluation."""
    return _dir(os.path.join(HERE, "candidates"), slug, os.path.join(HERE, "candidates"))


def ladder_dir(slug):
    """The demonstration ladder — deep save states training workers start episodes from.

    🔑 ONE definition, because there are already four consumers (make_ladder.py, train_worker's
    --swarm, run_weekend.ps1's summary, and now /api/train/ladder) and the last time this path
    was spelled out independently in three places they disagreed, so a ladder built by one tool
    was written where the others never looked and `--report` showed 0 states forever.

    ⚠️ Deliberately NOT namespaced under gpu-worker/<slug>/ for red: the directory already exists
    with that exact name on both the box and the training PC, and moving it would strand the very
    states this is meant to transport. A second game gets its own subdirectory.
    """
    base = os.path.join(HERE, "gpu-worker", "swarm")
    return base if slug == DEFAULT_SLUG else os.path.join(base, slug)


def runs_dir(slug):
    """Where promoted checkpoints live — what the broadcast loads from."""
    g = get(slug)
    return _dir(os.path.join(g.v2, "runs"), slug, os.path.join(g.v2, "runs"))


def results_file(slug):
    """Per-game eval history.

    ⚠️ Deliberately NOT one shared file. The metric vocabulary differs between games (Crystal has
    16 badges and an entirely different map-name set), so a shared table would hold scores that
    look comparable and are not.
    """
    return os.path.join(HERE, f"eval_results.{slug}.json") if slug != DEFAULT_SLUG \
        else os.path.join(HERE, "eval_results.json")


def zips(d):
    """*.zip in d, newest first. Missing dir is empty, not an error."""
    try:
        return sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".zip")),
                      key=os.path.getmtime, reverse=True)
    except OSError:
        return []


def current_checkpoint(slug=DEFAULT_SLUG):
    """🔑 THE one definition of "what this game is currently running": the newest zip in its
    runs/ dir. Every consumer must call this rather than re-globbing — that duplication is
    exactly what made promotion a file-mtime race across three files."""
    z = zips(runs_dir(slug))
    return z[0] if z else None


def candidates(slug=DEFAULT_SLUG):
    return zips(cand_dir(slug))


def promoted(slug=DEFAULT_SLUG):
    return zips(runs_dir(slug))


if __name__ == "__main__":
    for slug, g in GAMES.items():
        cur = current_checkpoint(slug) if g.available() else None
        print(f"{slug:9} {g.label:18} available={str(g.available()):5} badges={g.badges}")
        print(f"          runs       {runs_dir(slug)}")
        print(f"          candidates {cand_dir(slug)}")
        print(f"          results    {results_file(slug)}")
        print(f"          on air     {os.path.basename(cur) if cur else '(none)'}"
              f"   ({len(candidates(slug))} candidate(s) waiting)")
