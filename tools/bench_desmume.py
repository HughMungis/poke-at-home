#!/usr/bin/env python3
"""Measure whether a DS game can actually be emulated fast enough on this box.

  SDL_VIDEODRIVER=dummy ~/desmume-test/bin/python tools/bench_desmume.py --rom /path/to/hgss.nds

🔑 THIS NUMBER DECIDES THE DESIGN, so measure it before writing a spec. Our Game Boy environment
runs at ~38x realtime on these two ARM cores, which is why the nightly broadcast has to be
THROTTLED DOWN to look watchable. A DS renders 3D and two screens through a software rasteriser.
If HeartGold runs at 0.5x realtime here, then:
  - the box cannot broadcast it at all, and
  - training becomes entirely a job for Frank's PC,
which is a different project shape from the Game Boy one, decided by this measurement rather
than by hope.

WHAT REALTIME MEANS HERE: the DS runs at ~60 frames/second. So 60 fps measured = 1.0x realtime.
The Game Boy figure to beat, for comparison, is ~2,266 frames/second (38x of 59.7).

⚠️ Reports four separate costs, because they have different fixes. Raw stepping is the emulator;
frame extraction is the observation pipeline; memory reads are the reward function; save/load is
what episode resets and the swarm ladder pay on every reset.
"""
import argparse
import os
import statistics
import sys
import time

DS_FPS = 59.826          # the DS's actual refresh rate, not a rounded 60


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--frames", type=int, default=1800, help="frames per measurement (~30s of game)")
    ap.add_argument("--warmup", type=int, default=300)
    a = ap.parse_args()

    if not os.path.isfile(a.rom):
        print(f"no ROM at {a.rom}")
        return 1
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    from desmume.emulator import DeSmuME
    emu = DeSmuME()
    emu.open(a.rom)
    print(f"  ROM: {os.path.basename(a.rom)} ({os.path.getsize(a.rom)/1e6:.0f} MB)")

    for _ in range(a.warmup):
        emu.cycle()

    def rate(label, fn, n):
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        dt = time.perf_counter() - t0
        fps = n / dt
        print(f"  {label:34} {fps:9.1f} /s   {fps/DS_FPS:6.2f}x realtime")
        return fps

    print("\n=== throughput ===")
    raw = rate("emulate only", emu.cycle, a.frames)

    buf = []

    def with_frame():
        emu.cycle()
        buf.append(emu.display_buffer_as_rgbx())
        if len(buf) > 4:
            buf.pop(0)
    frame = rate("emulate + read both screens", with_frame, a.frames)

    mem = emu.memory

    def with_mem():
        emu.cycle()
        # A reward function reads on the order of 40 addresses per step (party, flags, coords).
        for addr in range(0x02000000, 0x02000000 + 40):
            mem.unsigned[addr]
    memr = rate("emulate + 40 memory reads", with_mem, min(a.frames, 600))

    print("\n=== state save/load (episode reset and swarm adoption pay this) ===")
    tmp = "/tmp/_ds_bench.dsv"
    ts = []
    for _ in range(5):
        t0 = time.perf_counter(); emu.savestate.save_file(tmp); ts.append(time.perf_counter()-t0)
    print(f"  save_file  median {statistics.median(ts)*1000:7.1f} ms")
    tl = []
    for _ in range(5):
        t0 = time.perf_counter(); emu.savestate.load_file(tmp); tl.append(time.perf_counter()-t0)
    print(f"  load_file  median {statistics.median(tl)*1000:7.1f} ms")
    try:
        os.unlink(tmp)
    except OSError:
        pass

    print("\n=== verdict ===")
    gb = 2266.0          # measured: the Game Boy env at 38x realtime on this box
    print(f"  Game Boy env on this box : {gb:.0f} frames/s ({gb/59.7:.0f}x realtime)")
    print(f"  DS here, with observation: {frame:.0f} frames/s ({frame/DS_FPS:.2f}x realtime)")
    print(f"  DS is {gb/max(frame,1e-9):.0f}x slower per frame than the Game Boy env")
    if frame >= DS_FPS * 4:
        print("  -> fast enough to broadcast AND to train here.")
    elif frame >= DS_FPS:
        print("  -> broadcastable (>=1x realtime) but too slow to train on this box; "
              "training belongs on the PC.")
    else:
        print("  -> BELOW REALTIME. The box cannot broadcast this game as-is. Reconsider before "
              "building a spec: a broadcast that runs slower than the game is not watchable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
