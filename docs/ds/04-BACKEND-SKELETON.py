"""Unwired emulator scaffolding; RedGymEnv continues using its existing PyBoy path.

Adopting this module requires the migration plan in 01-EMULATOR-SEAM.md:
capture the pinned baseline, introduce an opt-in path, audit callers and
subclasses, verify exact behavioral and operational parity, then stage and
promote between broadcasts with rollback available.

This module does not change action scheduling, observations, rewards, state
recovery, video handling, or deployment defaults. GameSpec remains responsible
for interpreting game memory.

screen_rgb() exposes the same first three channel values consumed by the
existing environment, without conversion or copying. Their RGB interpretation
must be verified against the pinned PyBoy build before adoption; it is not
established by the source's framebuffer comment.

DeSmuME is a stub only and introduces no native dependency.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, BinaryIO, Mapping

import numpy as np
from numpy.typing import NDArray


class Button(Enum):
    # Policy action indices depend on this exact order.
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    A = "a"
    B = "b"
    START = "start"


class Emulator(ABC):
    """Minimal emulator boundary; construction remains backend-specific."""

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
        """Advance the requested number of emulated frames.

        render=True refreshes the readable screen by completion.
        render=False permits skipping screen refresh, not emulation.
        Boundary handling for unusual frame counts belongs to the backend.
        """
        ...

    @abstractmethod
    def screen_rgb(self) -> NDArray[np.uint8]:
        """Return the configured display surface as H x W x 3 RGB.

        Do not resize or convert to grayscale. The caller must not mutate
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


class PyBoyEmulator(Emulator):
    """Pass through the PyBoy operations used by red_gym_env_v2.py.

    The native instance is exposed as ``pyboy`` for a future compatibility
    alias outside the ABC. Construction creates exactly one emulator.
    No state is loaded and no frames advance during adapter initialization.
    """

    def __init__(self, config: Mapping[str, Any]) -> None:
        from pyboy import PyBoy
        from pyboy.utils import WindowEvent

        self._press_events = {
            Button.DOWN: WindowEvent.PRESS_ARROW_DOWN,
            Button.LEFT: WindowEvent.PRESS_ARROW_LEFT,
            Button.RIGHT: WindowEvent.PRESS_ARROW_RIGHT,
            Button.UP: WindowEvent.PRESS_ARROW_UP,
            Button.A: WindowEvent.PRESS_BUTTON_A,
            Button.B: WindowEvent.PRESS_BUTTON_B,
            Button.START: WindowEvent.PRESS_BUTTON_START,
        }
        self._release_events = {
            Button.DOWN: WindowEvent.RELEASE_ARROW_DOWN,
            Button.LEFT: WindowEvent.RELEASE_ARROW_LEFT,
            Button.RIGHT: WindowEvent.RELEASE_ARROW_RIGHT,
            Button.UP: WindowEvent.RELEASE_ARROW_UP,
            Button.A: WindowEvent.RELEASE_BUTTON_A,
            Button.B: WindowEvent.RELEASE_BUTTON_B,
            Button.START: WindowEvent.RELEASE_BUTTON_START,
        }

        head = "null" if config["headless"] else "SDL2"
        self.pyboy = PyBoy(
            config["gb_path"],
            window=head,
            sound_emulated=bool(config.get("sound_emulated", False)),
        )
        if not config["headless"]:
            self.pyboy.set_emulation_speed(6)

    def read_u8(self, address: int) -> int:
        return self.pyboy.memory[address]

    def set_button(self, button: Button, pressed: bool) -> None:
        events = self._press_events if pressed else self._release_events
        self.pyboy.send_input(events[button])

    def tick(self, frames: int, render: bool) -> None:
        # Preserve arguments, including zero or negative frame counts.
        # The env retains its 8 / (action_freq - 9) / 1 scheduling.
        self.pyboy.tick(frames, render)

    def screen_rgb(self) -> NDArray[np.uint8]:
        # Preserve exactly the channels used by render() and _dialog_open().
        # No luminance conversion, reordering, resizing, or defensive copy.
        return self.pyboy.screen.ndarray[:, :, :3]

    def load_state(self, source: BinaryIO) -> None:
        self.pyboy.load_state(source)

    def save_state(self, destination: BinaryIO) -> None:
        self.pyboy.save_state(destination)

    def set_emulation_speed(self, multiplier: float) -> None:
        self.pyboy.set_emulation_speed(multiplier)


class DeSmuMEEmulator(Emulator):
    """Nonfunctional placeholder; no DeSmuME binding or API is assumed."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        raise NotImplementedError(
            "DeSmuME construction is unknown: select and verify a binding/core "
            "build, ROM-loading API, window/audio configuration, CPU memory "
            "view, and explicit display selection or composition."
        )

    def read_u8(self, address: int) -> int:
        raise NotImplementedError(
            "DeSmuME byte reads are unknown: verify the selected binding's "
            "memory API and explicitly choose the CPU address space."
        )

    def set_button(self, button: Button, pressed: bool) -> None:
        raise NotImplementedError(
            "DeSmuME input transitions are unknown: verify native button "
            "identifiers and how to preserve other held buttons when "
            "pressing or releasing one button."
        )

    def tick(self, frames: int, render: bool) -> None:
        raise NotImplementedError(
            "DeSmuME frame advancement is unknown: verify exact frame "
            "stepping, input processing, rendering suppression, and screen "
            "refresh semantics in the selected binding."
        )

    def screen_rgb(self) -> NDArray[np.uint8]:
        raise NotImplementedError(
            "DeSmuME framebuffer access is unknown: choose a display or "
            "documented composition and verify dimensions, pixel packing, "
            "channel order, buffer lifetime, and RGB conversion."
        )

    def load_state(self, source: BinaryIO) -> None:
        raise NotImplementedError(
            "DeSmuME state loading is unknown: verify native state "
            "compatibility, stream versus filename support, any required "
            "private temporary-file bridge, and partial-failure behavior."
        )

    def save_state(self, destination: BinaryIO) -> None:
        raise NotImplementedError(
            "DeSmuME state saving is unknown: verify serialization and "
            "stream versus filename support, including any required "
            "private temporary-file bridge."
        )

    def set_emulation_speed(self, multiplier: float) -> None:
        raise NotImplementedError(
            "DeSmuME pacing is unknown: verify whether the selected binding "
            "provides speed control or requires adapter-side wall-clock pacing."
        )
