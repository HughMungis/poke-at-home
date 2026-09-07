# The contributor image: one artifact that runs on Windows, macOS and Linux, on x86-64 and ARM.
#
# 🔑 THIS IMAGE HAS TWO JOBS, and that is deliberate rather than a coincidence:
#   1. It is what a volunteer runs to donate compute.
#   2. It is the SANDBOX the server uses to score a checkpoint uploaded by a stranger.
# An SB3 checkpoint is not data -- stable_baselines3/common/save_util.py calls cloudpickle.loads()
# on its metadata, so loading one executes whatever the author put in it. Scoring an untrusted
# checkpoint on the host would be remote code execution as a user with passwordless sudo. Using
# the same image for both means the sandbox is exercised continuously by real contributors
# instead of being a code path that only ever runs on hostile input.
#
# Build (multi-arch, from CI -- see docs/DISTRIBUTED.md for why not on the server):
#   docker buildx build --platform linux/amd64,linux/arm64 -f contrib/Dockerfile -t <tag> --push .
FROM python:3.12-slim

# Matches the server (Python 3.12.3). The version is not incidental: it decides which wheels
# exist, and pyboy in particular has no aarch64 wheel for older pins.

RUN apt-get update && apt-get install -y --no-install-recommends \
        libsdl2-2.0-0 \
    && rm -rf /var/lib/apt/lists/*
# ⚠️ pyboy links SDL2 even headless. Without libsdl2 the import fails at runtime rather than at
# build time, which would surface to a contributor as a crash in their first work unit.

WORKDIR /app

# torch FIRST and from the CPU index, so the pinned requirements below cannot pull the CUDA
# build in as a transitive dependency. ~200 MB instead of ~3 GB.
RUN pip install --no-cache-dir torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu

COPY contrib/requirements.txt /app/contrib/requirements.txt
RUN pip install --no-cache-dir -r /app/contrib/requirements.txt

# The environment and the scoring code, copied from this repo -- NOT cloned from upstream. Ours
# is a modified fork (see NOTICE) and the modifications are load-bearing: the required_events
# reward, the swarm hooks, and the gamespec seam. red_gym_env_v2.py imports gamespec.py, so
# copying only the env gets an ImportError several seconds into a run.
COPY repo/v2/ /app/repo/v2/
COPY gamereg.py eval_checkpoint.py make_ladder.py /app/
COPY contrib/worker.py /app/contrib/worker.py

# 🚨 NO ROM AND NO init.state ARE IN THIS IMAGE, and none may ever be added. The ROM is
# copyrighted; contributors dump their own cartridge. init.state is a memory dump of the ROM, so
# it is not ours to ship either -- it comes from the upstream project. Both arrive as read-only
# mounts at run time:
#
#   docker run --rm \
#     -v /path/to/PokemonRed.gb:/app/repo/PokemonRed.gb:ro \
#     -v /path/to/init.state:/app/repo/init.state:ro \
#     -e CONTRIB_TOKEN=... <image> eval
#
# The worker verifies the ROM's SHA1 on startup and refuses to run without it, so a wrong or
# truncated file fails immediately and loudly rather than producing quietly meaningless scores.

RUN useradd -m -u 1001 contrib && chown -R contrib:contrib /app
USER contrib
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Non-root because of job 2 above. When the server scores an untrusted checkpoint it adds
# --network none --read-only --cap-drop ALL and a pids/memory limit on top of this; see
# docs/DISTRIBUTED.md. That does not make container escape impossible, it moves an attacker from
# "calls PPO.load and is root" to "needs a kernel or Docker vulnerability".

ENTRYPOINT ["python3", "/app/contrib/worker.py"]
CMD ["--help"]
