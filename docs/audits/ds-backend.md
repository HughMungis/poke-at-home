I found serious silent-correctness defects. This is a static audit: local execution was unavailable, and the native-input findings below are traced through public dependency source rather than reproduced on your exact binary.

1. **High — `memory.py:121–158`: `verify()` positively identifies unrelated memory as game state.**

   Concrete input, with all integers stored little-endian:

   ```text
   Wrong anchor 0x02000080 contains 0x02010000.
   Actual save block is elsewhere, at 0x02080000.

   u16(0x02010000 + 0xD064) = 12345
   u32(0x02010000 + 0xD088 + i*0xEC)
       = 0x02020000 + i*4, for i = 0..5
   ```

   Call `verify(Memory(backend, 0x02000080), {"trainer_id": 12345})`.

   **Outcome: `True`.** Every sampled “PID” is just a RAM pointer: distinct, above `0xFFFF`, and non-ASCII. These checks do not measure entropy or establish that the bytes describe Pokémon. Matching the trainer ID does not rescue this example. `find_anchor()` also includes this wrong anchor among its hits.

   This is a constructed memory fixture, not a claim about your current ROM’s contents. It deterministically reaches the false acceptance you asked to attack.

2. **High — `backend.py:118–120, 173–175`: loading a state desynchronizes held keys, and `tick()` perpetuates it.**

   With a ROM loaded:

   ```python
   backend.press("RIGHT")
   backend.tick()
   backend.save_state("right.dst")
   backend.release_all()
   backend.load_state("right.dst")
   backend.tick(60)
   ```

   **Outcome: RIGHT is held in the emulator while `held()` returns an empty set.** The savestate restores input registers; Python’s `_keys` remains zero. Crucially, `cycle()` defaults to joystick processing, whose native path reads the restored keypad and writes it back—even without joystick events. Subsequent ticks preserve RIGHT until another Python keypad update occurs. [Python wrapper](https://raw.githubusercontent.com/SkyTemple/py-desmume/master/desmume/emulator.py), [native cycle](https://raw.githubusercontent.com/TASEmulators/desmume/master/desmume/src/frontend/interface/interface.cpp), [savestate implementation](https://raw.githubusercontent.com/TASEmulators/desmume/master/desmume/src/saves.cpp).

   Keeping a Python mask is therefore insufficient across state loads. Reopening a ROM likewise leaves `_keys` untouched; the next `press()` can reintroduce buttons retained from the previous session.

3. **Medium — `backend.py:118–120, 130–136`: pressing an unrelated button can reverse a sanitized D-pad direction.**

   Starting with released buttons and fresh direction history:

   ```python
   backend.press("UP")
   backend.press("DOWN")
   backend.tick()
   backend.press("A")
   backend.tick()
   ```

   **Outcome: the first tick delivers DOWN; the second delivers UP+A, although neither direction was released or newly pressed.**

   The sanitizer initially selects the newer DOWN. The first tick’s native keypad read/write feeds back only DOWN, resetting UP’s native hold counter. `press("A")` then resubmits Python’s UP|DOWN|A mask, so UP now appears newer and wins. Thus the action “press A” reverses movement. This follows the native direction counters and most-recent-direction rule. [Keypad sanitization](https://raw.githubusercontent.com/TASEmulators/desmume/master/desmume/src/frontend/posix/shared/ctrlssdl.cpp).

   The intended-versus-effective mask difference documented by `held()` is not itself the defect; changing the effective direction on an unrelated button press is.
