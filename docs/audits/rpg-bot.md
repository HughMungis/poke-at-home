1. **High — Any Twitch viewer can force authentication recovery and disconnect chat processing (lines 1110–1111, 1192–1197).**  
   The authentication check searches the entire raw IRC line, including user message text. A viewer posting `NOTICE Login authentication failed` triggers `PermissionError` before message parsing. The bot abandons its receive loop, refreshes its OAuth token, and reconnects despite valid authentication. Repeating this message after reconnections repeatedly interrupts Twitch commands and forces token refresh requests.

2. **Medium — A fight alias bypasses the off-air progression restriction (lines 199–203, 494–499).**  
   `!전투` routes to `engine.fight()` but is absent from `PROGRESS_CMDS`. With `REQUIRE_LIVE=True`, the nightly flag absent, and the relay reporting offline, a joined Twitch player sending `!fight` receives the closed response; sending `!전투` instead invokes combat. Players can continue fighting off-air through this alias.

These are the concrete defects I can establish from this file alone. I cannot substantiate format-string, path, SQL, or subprocess injection without the downstream implementations.
