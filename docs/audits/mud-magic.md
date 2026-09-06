- **`magic.py:122–137` — Mana spending is not atomic, contrary to its comment.** With 10 mana, two concurrent casts costing 8 can both read 10 before either writes. Both then store 2 and return `True`, allowing 16 mana worth of casting while deducting only 8.

- **`magic.py:118–119, 126–130` — Failed spending attempts discard fractional regeneration and can prevent recovery indefinitely.** With a mana cap of 55, stored mana 0, and timestamp 1000, retrying a 5-mana spell at every integer second regenerates only `55 / 300 ≈ 0.183` mana per attempt. Each attempt truncates this to 0 and stores a new timestamp. Mana stays at 0 forever instead of refilling over 300 seconds.

- **`magic.py:110, 125, 136` — An explicit simulation time of `0` is replaced by wall-clock time.** Starting with an uninitialized pool capped at 55, `spend_mana(char, 5, now=0)` stores 50 mana with a real-world timestamp. A subsequent `mana(char, now=1)` computes a large negative regeneration interval and returns 0, instead of approximately 50. This contradicts the documented support for threading simulated time through casting.

- **`party.py:62–72` — The minimum share of 1 violates the documented total-experience bound.** For five members sharing `bits=2`, each calculated share is 1, so five shares total 5 rather than the permitted 2. Even `bits=0` returns 1 per member, creating experience from a zero award.

- **`party.py:49–53` — Concurrent joins can exceed `GROUP_MAX`.** With four existing members, two new users can both execute `members(gid)` before either membership write and each observe a count of four. Both then join successfully, leaving six members despite the limit of five.
