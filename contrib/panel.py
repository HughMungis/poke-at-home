#!/usr/bin/env python3
"""The contributor's local control panel and visualiser (Phases 2 and 4).

Frank, 2026-09-07: "I don't want people to turn away from the project because it just looks like
a cli that they can't enjoy watching."

🔑 THE VISUALISER IS THIS PROJECT'S UNFAIR ADVANTAGE. Folding@home had to make a protein blob
look interesting; our unit of compute is literally a Game Boy screen. A contributor watching
their own machine play Pokemon is the retention mechanism, and it costs one PNG and a page.

🚨 BINDS 127.0.0.1 ONLY, and that is not a detail. This serves a live game screen and accepts
control requests with no authentication whatsoever; the security model is that it is unreachable
from off the machine. Binding 0.0.0.0 would publish an unauthenticated control surface on a
stranger's LAN. The port is only ever reachable through an explicit `docker run -p 127.0.0.1:...`
mapping.

⚠️ Everything here is best-effort. The panel is a nicety wrapped around real work: if it fails to
start, fails to render, or the browser is never opened, the worker must carry on scoring exactly
as it would have. Every entry point is therefore wrapped, and none of them can raise into the
work loop.
"""
import http.server
import io
import json
import threading
import time

PORT = 7397

# One shared dict. The worker writes it; the request handler reads it. Python dict assignment is
# atomic under the GIL and every field is independently meaningful, so a reader can never see a
# torn value that matters -- which is why this needs no lock and cannot deadlock the work loop.
STATE = {
    "job": None, "checkpoint": None, "seed": None, "steps": 0, "started": None,
    "run": 0, "runs": 0, "maps": 0, "tiles": 0, "badges": 0, "stage": 0,
    "results_sent": 0, "states_sent": 0, "handle": None, "paused": False,
    "last_frame_ts": 0.0, "note": "starting up",
}
_FRAME = {"png": None}          # latest game screen, already encoded
_FRAME_EVERY = 0.25             # seconds; ~4 fps is plenty for a Game Boy and costs nothing


def publish_frame(env):
    """Encode the current screen if enough time has passed. Called from the step loop.

    ⚠️ Throttled HERE rather than by the caller, so the eval loop stays dumb and this cannot
    accidentally be called at 160 Hz by a future caller that forgets.
    """
    now = time.time()
    if now - STATE["last_frame_ts"] < _FRAME_EVERY:
        return
    try:
        from PIL import Image
        arr = env.pyboy.screen.ndarray[:, :, :3]     # RGBA -> RGB
        img = Image.fromarray(arr).resize((320, 288), Image.NEAREST)  # integer 2x, no shimmer
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        _FRAME["png"] = buf.getvalue()
        STATE["last_frame_ts"] = now
    except Exception:
        pass          # a missing frame is invisible; an exception here would stop the scoring


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>poke-at-home</title>
<style>
:root{color-scheme:dark}
body{background:#12100f;color:#e9e6e3;font:15px/1.5 system-ui,-apple-system,sans-serif;
  margin:0;padding:20px;display:flex;flex-direction:column;align-items:center;gap:14px}
h1{font-size:1rem;color:#8d8681;font-weight:600;margin:0;letter-spacing:.04em;text-transform:uppercase}
#screen{image-rendering:pixelated;width:320px;height:288px;background:#000;border:1px solid #2a2521;
  border-radius:6px}
.card{background:#1a1613;border:1px solid #2a2521;border-radius:8px;padding:14px 16px;width:320px}
.row{display:flex;justify-content:space-between;padding:3px 0;font-size:.92rem}
.k{color:#8d8681} .v{font-variant-numeric:tabular-nums}
button{background:#e0803a;color:#12100f;border:0;border-radius:6px;padding:9px 16px;
  font:inherit;font-weight:600;cursor:pointer;width:100%}
button.off{background:#2a2521;color:#e9e6e3}
.note{color:#8d8681;font-size:.85rem;text-align:center;max-width:320px}
</style></head><body>
<h1>Your machine, playing Pokemon</h1>
<img id=screen alt="live game screen">
<div class=card id=stats></div>
<div class=card><button id=pause></button></div>
<p class=note id=note></p>
<script>
const $=i=>document.getElementById(i);
function rows(d){
  const r=[['job',d.job||'—'],['checkpoint',(d.checkpoint||'—').replace('.zip','')],
           ['run',d.runs?`${d.run} of ${d.runs}`:'—'],['steps',(d.steps||0).toLocaleString()],
           ['map regions',d.maps],['tiles seen',(d.tiles||0).toLocaleString()],
           ['badges',d.badges],['story stage',d.stage+' of 17'],
           ['results sent',d.results_sent],['states sent',d.states_sent]];
  return r.map(([k,v])=>`<div class=row><span class=k>${k}</span><span class=v>${v}</span></div>`).join('');
}
async function tick(){
  try{
    const d=await (await fetch('/status.json',{cache:'no-store'})).json();
    $('stats').innerHTML=rows(d);
    $('note').textContent=d.note||'';
    $('pause').textContent=d.paused?'Resume contributing':'Pause after this run';
    $('pause').className=d.paused?'off':'';
    // cache-bust so the browser actually refetches the frame
    $('screen').src='/frame.png?t='+Date.now();
  }catch(e){ $('note').textContent='worker not responding'; }
}
$('pause').onclick=async()=>{ await fetch('/toggle',{method:'POST'}); tick(); };
tick(); setInterval(tick,1000);
</script></body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass          # the browser navigated away mid-frame; not an error

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if p == "/status.json":
            return self._send(200, json.dumps(STATE).encode(), "application/json")
        if p == "/frame.png":
            png = _FRAME["png"]
            if not png:
                return self._send(404, b"no frame yet", "text/plain")
            return self._send(200, png, "image/png")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path == "/toggle":
            STATE["paused"] = not STATE["paused"]
            return self._send(200, json.dumps({"paused": STATE["paused"]}).encode(),
                              "application/json")
        self._send(404, b"not found", "text/plain")

    def log_message(self, *a):
        pass          # the panel is not the worker's log


def start(port=PORT):
    """Start the panel in a daemon thread. Returns the URL, or None if it could not bind.

    ⚠️ Never raises. A port already in use (two workers on one machine) must not stop either of
    them from doing the actual work.
    """
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    except OSError:
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"
