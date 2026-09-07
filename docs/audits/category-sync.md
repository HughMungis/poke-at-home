Found serious defects, including failures that bypass the alarm and updates that never retry.

1. **High — SOOP failures are permanently acknowledged as synced. Lines 475–509, 529.**  
   Scenario: Twitch changes from game A to B. CHZZK succeeds, but SOOP raises `SoopAuthError` or a transient network error. The exception is swallowed and `last_game`/`last_title` are saved as B’s values. Subsequent unchanged polls never retry SOOP—even after its cookie is repaired—and reset the failure alarm. SOOP remains on A until another relevant Twitch change. The initial Discord message is the only notification attempt.

2. **High — Persistent YouTube errors never trigger the failure alarm. Lines 514–529.**  
   Scenario: `youtube_adapter.sync()` raises a network error every poll during a prolonged outage. Line 528 logs it, then line 529 calls `note_cycle()` with no error, resetting the streak. YouTube can fail indefinitely without a sustained-failure notification.

3. **High — Token and state saves can destroy the existing file. Lines 55–62, 189–194, 508–509.**  
   Scenario: `cz_refresh()` receives valid replacement tokens, then `jsave()` truncates `tokens.json`. The process is killed before writing the replacement JSON. On restart, `jload()` silently returns `{}`; `cz_call()` raises “No CHZZK tokens” before reaching refresh handling. Recovery requires manual authorization or restoring tokens. The same truncation window exposes empty or partial JSON to other processes reading state; there is no atomic replacement.

4. **High — A failed alarm delivery suppresses all further failure alerts. Lines 85–109, 127–132.**  
   Scenario: five consecutive Twitch failures trigger the alarm while Discord is temporarily unavailable. `_fail["alerted"]` is set **before** delivery; `discord()` catches delivery failures and returns normally. Discord recovers, but Twitch continues failing for four days. No further failure notification is attempted during those four days. Missing fallback credentials also silently consume the alert.

5. **High — CHZZK failure indefinitely prevents otherwise healthy platforms from syncing. Lines 459–468, 474–515, 530–533.**  
   Scenario: Twitch changes to B, but CHZZK’s refresh token has been revoked. `cz_set_category()` attempts refresh and raises. Execution skips both SOOP and YouTube and never commits B as `last_game`. Every subsequent poll repeats this path, so both healthy platforms remain stale until CHZZK is repaired. This path does reach the failure alarm, subject to finding 4.

6. **Medium — A failed manual CHZZK title update has no automatic recovery. Lines 260–267, 467–468, 504–509.**  
   Scenario: `title "New title"` saves the override, but the CHZZK request times out without applying it. Later polls compute `override=True` and explicitly skip CHZZK title updates—even when the Twitch title changes. CHZZK keeps its old title indefinitely while SOOP may show the new override, contradicting the shared-title rule. Repeating the command or clearing the override is required.

7. **Medium — Nightly mode also disables YouTube synchronization. Lines 432–438, 511–515.**  
   Scenario: the nightly job refreshes the flag every five seconds for eight hours. The early `continue` skips Twitch reads and YouTube synchronization for all eight hours, although the stated pause concerns CHZZK/SOOP. A YouTube broadcast starting during that period is never renamed within one poll as promised.

8. **Medium — Initial fallback lookup failures bypass the alarm entirely. Lines 413–419.**  
   Scenario: a fresh installation has no cached `fallback`, and CHZZK category search returns HTTP 503. The exception occurs before the loop’s handler, terminating the process without calling `note_cycle()`. Repeated service restarts during the outage repeat the same failure without ever accumulating an alert streak.
