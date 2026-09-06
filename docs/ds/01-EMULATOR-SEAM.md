# Emulator Abstraction Design — Blocked on Source Access

I could not read `repo/v2/red_gym_env_v2.py` or `repo/v2/gamespec.py`. Both file-read attempts failed before execution:

```text
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

No alternative repository-reading resource is available. Without the files, I cannot truthfully inventory every PyBoy interaction, quote real line numbers, or restrict the proposed interface to operations the environment actually uses.

Please provide the contents of both files or restore workspace command execution. The design can then include the verified call inventory, minimal Python ABC, emulator-specific compatibility constraints, and a staged migration that protects the live Red broadcast.
