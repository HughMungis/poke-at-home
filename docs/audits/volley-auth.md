1. **High — Revoked RPG sessions become valid when the revocation check fails (lines 252–257).**  
   Scenario: a player’s stolen, unexpired cookie contains epoch `k=0`. The player runs `!unlink`, advancing their epoch to `1`. During a subsequent request, `link_epoch()` raises—for example, because its database is temporarily unavailable. The exception is swallowed and `rpg_session_user()` returns the player’s username, accepting the revoked cookie. This is an explicit fail-open authentication check. Whether a subsequent write succeeds depends on the omitted handlers and engine.

2. **Medium — Concurrent killswitch calls lose audit records (lines 1064–1082).**  
   Scenario: threads A and B both read history `H`. A records `stop`, writes and replaces the temporary file successfully. B then writes its previously computed `H + enable` and replaces the log. The final log contains `enable` but loses `stop`. Atomic replacement does not protect the read-modify-write operation; the claimed audit trail misses a completed action.

3. **Medium — Failed title updates are reported and remembered as successful (lines 824–830).**  
   Scenario: `/usr/local/bin/settitle` exits with status `1` after an API rejects the update. `subprocess.run()` returns normally because `check=True` is absent, and the return code is ignored. The server announces that the title is set on both platforms and updates `_last_pushed`. A subsequent “sync word of the day” uses the rejected title even though it was never published.

**Scope:** These 1,200 lines contain no HTTP handlers or server startup. I cannot establish an outside-gate write, static-path traversal, request-body/thread exhaustion, or endpoint-level exploit from this excerpt. I found no session-cookie forgery in the shown signing and verification code.
