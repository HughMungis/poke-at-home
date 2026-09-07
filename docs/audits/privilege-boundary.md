**The privilege boundary cannot be verified from these excerpts.** They contain neither the request-file writer nor the root-side consumer or systemd units. No concrete root-boundary exploit—or conclusion that the boundary holds—is supported by the supplied code.

Two request-integrity defects are visible in the training API, although neither is shown to reach the privileged spool:

| Lines | Defect and mechanism | Concrete request sequence |
|---|---|---|
| 3103–3106, 3123–3135 | **Replay protection trusts caller-selected IDs.** A nonempty `result_id` replaces the content fingerprint, allowing identical results to be stored repeatedly under different IDs. | With a valid `X-Train-Token`, POST a valid result to `/api/train/eval-result` with `result_id: "a"`. Repeat the identical scoring payload with IDs `"b"` through `"e"`. All five entries are stored. Whether they cause promotion requires inspecting the downstream consumer. |
| 3103, 3123–3130 | **One submission can suppress another.** IDs are truncated to 64 characters and deduplicated across the selected game's entire history without checking that the payload matches. | Caller A submits a valid result with ID `"shared"`. Caller B submits a different checkpoint/result for the same game with ID `"shared"`. B receives HTTP 200 with `duplicate: true`, and its result is discarded. Distinct IDs sharing their first 64 characters also collide. Both callers need the training token. |

The shown token gates reject unconfigured tokens and use `hmac.compare_digest` before performing API operations (2940–2943 and 3001–3005). **No token bypass or secret-prefix timing attack is demonstrated here.** Route dispatch and session validation are absent, so their checks cannot be assessed.

To finish the requested boundary audit, the missing evidence is:

- Request-file creation code, including filenames, serialization, and publication.
- Root consumer code, including validation, execution, deletion, and replay handling.
- Systemd service/path units and spool ownership, permissions, and parent-directory permissions.

`NoNewPrivileges=yes` does not constrain the independently running root consumer. Its treatment of files writable by the compromised server is the decisive boundary.
