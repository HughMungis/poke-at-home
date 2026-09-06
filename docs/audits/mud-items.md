- **`items.py:101–104` — Failed destruction still deletes contents.** Bag 10 contains sword 11. A command reads the bag at `(CARRIED, "alice")`; another command moves it to Bob. Calling `destroy(10, expect=(CARRIED, "alice"))` deletes sword 11 before checking the bag’s location. The bag deletion fails and returns `False`, but Bob’s sword is permanently lost.

- **`items.py:101–103, 426–427` — Container deletion leaves nested contents orphaned.** Corpse 10 contains bag 11, which contains sword 12. Destroying or decaying corpse 10 deletes bag 11 and the corpse, but leaves sword 12 with `container_id=11`. The sword is unreachable through normal location resolution, and repeated deaths with filled bags accumulate orphaned rows.

- **`items.py:195–197` — Capacity checks omit the incoming container’s contents.** An empty bag with capacity 25 accepts another bag weighing 2 that contains items weighing 24: the check sees only `0 + 2 <= 25`. After moving it inside, the destination’s load is 26, exceeding its capacity.

- **`items.py:193–194` — Nesting checks omit the incoming container’s descendants.** Bag A already contains bag B. Putting A into empty, top-level bag C passes because `depth_of(C)` is 1. The resulting chain C → A → B has three container levels despite `MAX_NESTING = 2`.

- **`gear.py:151–162` — Concurrent equips can occupy the same equipment slot.** Alice carries swords 10 and 11 and has no equipped weapon. Two calls to `equip` both read an empty right-hand slot before either writes. One equips sword 10 and commits; the other equips sword 11 and commits without removing sword 10. Both return success and both rows remain worn, while `worn()` exposes only sword 10, silently hiding the second equipped weapon.

- **`gear.py:322–325, 339–352` — Mythic awards are not once per character per world.** Alice receives a world’s mythic, then puts it inside a bag; `items.move()` clears its `owner`. `has_mythic()` now returns false, so another successful boss roll awards a second copy while she still possesses the first. Dropping, selling, or losing the original also permits another award because no permanent award record is checked.
