# Emulator abstraction design

## Scope and boundary

Introduce an `Emulator` interface between `RedGymEnv` and the emulator library. Keep `GameSpec` responsible for game memory interpretation and map layout.

This fits the existing boundary: `gamespec.py:131–133` explicitly accepts a `read_m(addr) -> int` callable without retaining an emulator. `RedGymEnv.read_m` can delegate to the new backend without changing any spec methods.

This document cites the supplied, numbered versions of `repo/v2/red_gym_env_v2.py` and `repo/v2/gamespec.py`. It proposes a design; it does not claim a tested DeSmuME implementation.

## 1. PyBoy dependency inventory

All line numbers in this section refer to `red_gym_env_v2.py`.

### Imports and construction

| Lines | Quoted source | Dependency |
|---|---|---|
| 10 | `from pyboy import PyBoy` | Concrete emulator class. |
| 16 | `from pyboy.utils import WindowEvent` | Emulator-specific input constants. |
| 251 | `head = "null" if config["headless"] else "SDL2"` | PyBoy window configuration. |
| 254–269 | Constructor quoted below. | ROM loading, window selection, and audio emulation. |
| 274 | `self.pyboy.set_emulation_speed(6)` | Speed setting, only when not headless (273). |

The active constructor expressions are:

```python
self.pyboy = PyBoy(                                      # 254
    config["gb_path"],                                  # 255
    window=head,                                        # 258
    sound_emulated=bool(config.get("sound_emulated", False)),  # 268
)                                                       # 269
```

### Input constants and their consumers

Each constant is part of the policy’s ordered action mapping.

| Press line and quoted constant | Release line and quoted constant |
|---|---|
| 121: `WindowEvent.PRESS_ARROW_DOWN` | 131: `WindowEvent.RELEASE_ARROW_DOWN` |
| 122: `WindowEvent.PRESS_ARROW_LEFT` | 132: `WindowEvent.RELEASE_ARROW_LEFT` |
| 123: `WindowEvent.PRESS_ARROW_RIGHT` | 133: `WindowEvent.RELEASE_ARROW_RIGHT` |
| 124: `WindowEvent.PRESS_ARROW_UP` | 134: `WindowEvent.RELEASE_ARROW_UP` |
| 125: `WindowEvent.PRESS_BUTTON_A` | 135: `WindowEvent.RELEASE_BUTTON_A` |
| 126: `WindowEvent.PRESS_BUTTON_B` | 136: `WindowEvent.RELEASE_BUTTON_B` |
| 127: `WindowEvent.PRESS_BUTTON_START` | 137: `WindowEvent.RELEASE_BUTTON_START` |

Additional coupling through those constants:

| Lines | Quoted source | Dependency |
|---|---|---|
| 159 | `self.action_space = spaces.Discrete(len(self.valid_actions))` | Action-space cardinality follows the PyBoy event list. |
| 247 | `"recent_actions": spaces.MultiDiscrete([len(self.valid_actions)] * self.frame_stacks)` | Observation schema follows the same list. |
| 409–410 | `self.update_seen_interactions(self.valid_actions[action] if action < len(self.valid_actions) else None)` | Passes a native event into reward logic. |
| 581 | `if (opened and action != WindowEvent.PRESS_BUTTON_START` | Reward logic directly compares a native constant. |

### Runtime calls and properties

| Line | Quoted source | Operation |
|---|---|---|
| 291 | `self.pyboy.load_state(f)` | Load initial state during reset. |
| 363 | `game_pixels_render = self.pyboy.screen.ndarray[:,:,0:1]` | Read first screen channel for observations and rendering. |
| 450 | `self.pyboy.send_input(self.valid_actions[action])` | Press selected button. |
| 454 | `self.pyboy.tick(press_step, render_screen)` | Advance eight frames while held. |
| 455 | `self.pyboy.send_input(self.release_actions[action])` | Release selected button. |
| 456 | `self.pyboy.tick(self.act_freq - press_step - 1, render_screen)` | Advance remaining frames except the last. |
| 457 | `self.pyboy.tick(1, True)` | Advance final frame with rendering enabled. |
| 550 | `return float(self.pyboy.screen.ndarray[r0:r1, c0:c1, :3].mean()) > self.DIALOG_THRESH` | Read three screen channels for dialogue detection. |
| 768 | `return self.pyboy.memory[addr]` | Read one memory byte; feeds all GameSpec accessors. |
| 856 | `self.pyboy.save_state(f)` | Serialize a swarm state before atomic publication. |
| 898 | `self.pyboy.load_state(f)` | Adopt a swarm state. |
| 905 | `self.pyboy.load_state(f)` | Restore initial state after failed adoption. |

### Inactive references and surrounding assumptions

These are not additional runtime operations:

- **11:** `#from pyboy.logger import log_level`
- **253:** `#log_level("ERROR")`
- **256–257:** `#debugging=False,` and `#disable_input=False,`
- **271:** `#self.screen = self.pyboy.botsupport_manager().screen()`
- **767:** `#return self.pyboy.get_memory_value(addr)`

Comments at **259–267** document audio behavior; **859–860** explain catching PyBoy save exceptions; **890–894** describe version-incompatible state loads.

Screen consumers also encode platform assumptions: `(72, 80, self.frame_stacks)` at **155**, downscaling at **366–367**, `(144, 160)` and `fps=60` for full-frame video at **503**, and dialogue coordinates and threshold at **545–546**. These are not direct PyBoy accesses, but replacing the emulator alone will not make them appropriate for DS.

There is no active memory write, touchscreen input, audio-buffer read, emulator shutdown, or separate ROM-reset call in this file. None belongs in the initial interface.

## 2. Minimal interface

Seven methods cover the operations actually used. Construction remains backend-specific and outside the ABC.

```python
from abc import ABC, abstractmethod
from enum import Enum
from typing import BinaryIO

import numpy as np
from numpy.typing import NDArray


class Button(Enum):
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    A = "a"
    B = "b"
    START = "start"


class Emulator(ABC):
    @abstractmethod
    def read_u8(self, address: int) -> int:
        """Read one unsigned byte from the configured CPU address space."""
        ...

    @abstractmethod
    def set_button(self, button: Button, pressed: bool) -> None:
        """Apply a button transition before the next frame advances."""
        ...

    @abstractmethod
    def tick(self, frames: int, render: bool) -> None:
        """Advance exactly this many emulated frames.

        render=True refreshes the readable screen by completion.
        render=False permits skipping screen refresh, not emulation.
        """
        ...

    @abstractmethod
    def screen_rgb(self) -> NDArray[np.uint8]:
        """Return the configured display surface as H×W×3 RGB.

        No resizing or grayscale conversion. The caller must not mutate
        the result or retain it across tick/load operations without copying.
        """
        ...

    @abstractmethod
    def load_state(self, source: BinaryIO) -> None:
        """Load opaque native state from a seekable binary stream.

        Failure may leave emulator state partially modified.
        The caller owns and closes the stream.
        """
        ...

    @abstractmethod
    def save_state(self, destination: BinaryIO) -> None:
        """Write opaque native state to a seekable binary stream.

        The caller owns and closes the stream.
        """
        ...

    @abstractmethod
    def set_emulation_speed(self, multiplier: float) -> None:
        """Set wall-clock pacing relative to native speed."""
        ...
```

### Mapping and contracts

| Interface operation | PyBoy adapter |
|---|---|
| `read_u8(address)` | `pyboy.memory[address]` |
| `set_button(button, pressed)` | Explicit lookup of press/release `WindowEvent`, followed by `send_input`. |
| `tick(frames, render)` | Forward unchanged to `pyboy.tick(frames, render)`. |
| `screen_rgb()` | Return the verified RGB channels from `pyboy.screen.ndarray`. |
| `load_state(source)` | `pyboy.load_state(source)` |
| `save_state(destination)` | `pyboy.save_state(destination)` |
| `set_emulation_speed(multiplier)` | `pyboy.set_emulation_speed(multiplier)` |

The factory preserves `gb_path`, `headless`, and `sound_emulated=False` exactly as currently configured at **251–269**. Window names and audio initialization belong inside backend construction, not in `GameSpec`.

Preserve the policy index order as **DOWN, LEFT, RIGHT, UP, A, B, START**. Replace the START comparison at **581** with `Button.START`. The release list becomes unnecessary because `set_button` expresses both transitions.

Keep action scheduling in the env:

```python
button = self.valid_actions[action]
self.emulator.set_button(button, True)
render_screen = self.save_video or not self.headless
self.emulator.tick(8, render_screen)
self.emulator.set_button(button, False)
self.emulator.tick(self.act_freq - 9, render_screen)
self.emulator.tick(1, True)
```

Do not change boundary handling for unusual `action_freq` values during this refactor; first characterize the existing behavior.

A DeSmuME adapter can implement the same operations using its selected binding. Any filename-only state API would require a private temporary-file bridge. Pacing may require adapter-side implementation. Exact native calls and framebuffer conversion must be verified against the chosen binding and build before claiming conformance.

## 3. Awkward cases

### Save states are native, version-locked artifacts

A shared `load_state` signature does **not** create a portable state format. Treat state compatibility as locked to emulator/core build, ROM identity, and relevant configuration unless explicitly verified otherwise. The existing source already documents a newer-PyBoy-state rejection at **890–894**.

For new runs, record that compatibility identity in run metadata and isolate swarm directories accordingly. Keep existing Red state files and paths usable under their pinned deployment; do not require new headers or rewrite legacy files during migration.

Preserve the temporary-write/atomic-rename sequence at **854–857**, adoption before reward baselines at **298–343**, and initial-state restoration after load failure at **901–908**.

The current recovery code suppresses even restoration failures at **906–907**. The interface must not promise transactional loads or guaranteed recovery. Improving that behavior is a separate change.

### Screen normalization must preserve Red pixels

The inline comment at **363** is not proof of the runtime buffer’s channel count or order. Verify the pinned PyBoy buffer before implementing conversion.

For Red, `screen_rgb()` must preserve the exact first three values previously consumed. The env must still select channel zero at **363**, rather than introduce luminance conversion, and retain the three-channel mean at **550**. Dropping unused alpha is acceptable only after verifying channel order.

Different backends may expose packed pixels, different channel order, or different buffer layouts. Normalize those mechanically inside the adapter, while preserving native dimensions. Pixel equality is part of acceptance, not merely visual similarity.

### Button identity and timing differ

Native button values never leave an adapter. A DeSmuME implementation must preserve held-button state when translating transitions into its native input representation.

Do not replace the existing eight-frame hold with a library convenience “press” call whose release timing may differ. Rendering suppression must not change elapsed emulation or input processing.

### DS requires additional design beyond this interface

DS has two screens and a touchscreen. The proposed minimal interface exposes one explicitly configured display surface. A DS experiment must choose a screen or a documented composition during construction; the adapter must not silently discard a screen or resize both into Red’s observation shape.

That choice still requires a separate observation design. Red’s dimensions, dialogue heuristic, and video settings remain game/platform-specific. Touch coordinates, contact state, and DS-only buttons are intentionally absent because this env never uses them. Add them only with a concrete DS action space and caller.

Similarly, `read_u8` addresses the backend’s explicitly configured CPU memory view. A DS spec must identify the appropriate view and implement its own game structures; Red’s two-byte HP interpretation (`gamespec.py:198–199`) is not a universal emulator rule.

Implementing this ABC therefore enables a backend boundary, not a drop-in DS port or reuse of Red checkpoints.

## 4. Migration without interrupting Red

1. **Capture the pinned baseline.** Record the deployed code, PyBoy build, ROM identity, configuration, checkpoint, and save states. Run the existing snapshot procedure referenced at **38–41** and GameSpec tests described in `gamespec.py:13–15`. Capture deterministic action traces with observations, rewards, memory reads, and rendered pixels.

2. **Add the ABC and PyBoy adapter without changing execution.** Place supporting modules beside the env in `repo/v2/`. Preserve the deployment layout requirement documented at **18–29** and `gamespec.py:29–40`. Keep DeSmuME imports optional and isolated so Red requires no new native dependency.

3. **Introduce an opt-in adapter path.** Keep the existing path as the default. Route memory, states, screens, inputs, and pacing through the adapter incrementally, checking parity after each change. Do not change observation keys, dtypes, shapes, action indices, reward logic, or configuration defaults.

4. **Audit callers and subclasses before promotion.** Search broadcast, training, evaluation, and capture code for direct `.pyboy` access and overrides. The source identifies `nightly.py` subclassing at **67** and its audio requirement at **265**. Temporarily retain `self.pyboy` as an alias to the same native instance for PyBoy callers that need compatibility. Never create a second emulator. Keep this escape hatch outside the ABC.

5. **Require behavioral and operational parity.** Replay identical traces from at least the baseline save states. Compare every observation array and reward component exactly, including dialogue transitions and START exclusion. Exercise state round trips, swarm adoption and failure recovery, visible/headless modes, video modes, and broadcast audio. Load the existing checkpoint and perform a sustained staging broadcast while checking throughput and memory.

6. **Promote between broadcasts with immediate rollback available.** Deploy the tested module set together and retain the prior release, dependencies, configuration, and native states. Switch the default to the adapter only after staging passes; retain the legacy-path switch during the rollout. Do not upgrade PyBoy or migrate states in the same release.

7. **Develop DeSmuME independently.** Use separate configuration, game specs, state directories, observation/action schemas, and checkpoints. Add touchscreen or multi-screen interface extensions when that environment actually consumes them. Remove Red’s temporary compatibility path only after caller audits and successful daily operation establish that it is unused.

The release gate is unchanged Red behavior and successful broadcast operation at every stage; DS support must not become a dependency of the live Red pipeline.
