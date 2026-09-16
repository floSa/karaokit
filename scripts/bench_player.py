"""Test de bout en bout du lecteur Karaokit dans un vrai navigateur (Chromium headless).

Usage (depuis la racine, après `cd web && npm run build`) :
  uvx --with playwright playwright install chromium        # une fois
  uv run --with playwright python scripts/bench_player.py web/dist web/public/library local [slug …] [--throttle MBPS] [--cpu N]

--throttle 10 : réseau limité à 10 Mbit/s (téléphone/TV en Wi-Fi) ;
--cpu 4       : processeur bridé ×4 (appareil modeste).
Démarre karaoke.server sur un port libre avec app_dir/lib_dir, puis mesure :
  - délai clic morceau -> lecteur prêt -> 1er son (time-to-play)
  - octets téléchargés avant de pouvoir jouer
  - seek à 60 s : la position est-elle respectée ?
  - fluidité (fps, long tasks) pendant 8 s de lecture
  - précision du surlignage (mot actif DOM vs timecodes JSON)
  - dérive voix-guide / instrumental
"""
import json
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from karaoke import server as ksrv  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

app_dir, lib_dir, label = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
throttle = float(sys.argv[sys.argv.index("--throttle") + 1]) if "--throttle" in sys.argv else None
argv = sys.argv[4:]
cpu_rate = float(sys.argv[sys.argv.index("--cpu") + 1]) if "--cpu" in sys.argv else None
for flag in ("--throttle", "--cpu"):
    if flag in argv:
        i = argv.index(flag); del argv[i:i + 2]
slugs = argv

s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
httpd = ThreadingHTTPServer(("127.0.0.1", port), ksrv.make_handler(app_dir, lib_dir))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"

index = json.loads((lib_dir / "index.json").read_text())
slugs = slugs or [e["slug"] for e in index]
results = {}

with sync_playwright() as p:
    browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    for slug in slugs:
        entry = next(e for e in index if e["slug"] == slug)
        data = json.loads((lib_dir / slug / "karaoke.json").read_text())
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        if throttle:
            bps = throttle * 1e6 / 8
            cdp.send("Network.emulateNetworkConditions", {
                "offline": False, "latency": 20, "downloadThroughput": bps, "uploadThroughput": bps})
        received = {"bytes": 0}
        cdp.on("Network.dataReceived", lambda e: received.__setitem__("bytes", received["bytes"] + e["encodedDataLength"]))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))

        page.goto(base + "/")
        page.wait_for_selector(".songlist button")
        received["bytes"] = 0
        title = entry["title"] or slug
        t0 = time.perf_counter()
        page.locator(".songlist button", has_text=title).first.click()
        page.wait_for_selector(".controls .play", timeout=30000)
        t_player = time.perf_counter() - t0
        # Clic play immédiat, comme un utilisateur.
        page.click(".controls .play")
        # 1er son = currentTime avance réellement.
        page.wait_for_function("() => { const a=document.querySelector('audio'); return a && !a.paused && a.currentTime > 0.05; }", timeout=120000)
        t_sound = time.perf_counter() - t0
        bytes_before_sound = received["bytes"]

        # Seek à 60 s via le scrubber (comme un utilisateur).
        seek_target = min(60.0, max(5.0, data.get("duration", 200) / 2))
        page.evaluate("""(t) => { const r=document.querySelector('.scrub');
            const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            set.call(r, String(t)); r.dispatchEvent(new Event('input',{bubbles:true})); }""", seek_target)
        ts = time.perf_counter()
        try:
            page.wait_for_function("(t) => { const a=document.querySelector('audio'); return Math.abs(a.currentTime - t) < 1.5 && !a.paused && a.readyState >= 3; }", arg=seek_target, timeout=30000)
            seek_ok, seek_lat = True, time.perf_counter() - ts
        except Exception:
            seek_ok, seek_lat = False, None
        pos_after_seek = page.evaluate("() => document.querySelector('audio').currentTime")

        # Fluidité + précision pendant 8 s (CPU éventuellement bridé façon mobile).
        if cpu_rate:
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": cpu_rate})
        cdp.send("Performance.enable")
        m0 = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
        stats = page.evaluate("""(words) => new Promise(res => {
            const a = document.querySelectorAll('audio');
            const instru = a[0], voc = a[1];
            let frames = 0, longTasks = 0, longMs = 0, errs = [], drift = [];
            const po = new PerformanceObserver(l => l.getEntries().forEach(e => { longTasks++; longMs += e.duration; }));
            try { po.observe({entryTypes:['longtask']}); } catch(e) {}
            const start = performance.now();
            let mutations = 0;
            const mo = new MutationObserver(m => mutations += m.length);
            mo.observe(document.querySelector('.lyrics') || document.body, {subtree:true, attributes:true, childList:true, characterData:true});
            const tick = () => {
              frames++;
              const t = instru.currentTime;
              if (voc && !voc.paused) drift.push(Math.abs(voc.currentTime - t));
              const cur = words.find(w => t >= w.start + 0.05 && t < w.end - 0.05);
              if (cur) {
                const el = document.querySelector('.line.active .word.singing, .line.active .word.active');
                const txt = el ? el.textContent.trim() : null;
                errs.push(txt === cur.text ? 0 : 1);
              }
              if (performance.now() - start < 8000) requestAnimationFrame(tick);
              else { po.disconnect(); mo.disconnect();
                res({fps: frames / 8, longTasks, longMs, checked: errs.length,
                     wrong: errs.reduce((x,y)=>x+y,0), mutationsPerSec: mutations/8,
                     driftMax: drift.length ? Math.max(...drift) : null,
                     driftMed: drift.length ? drift.sort()[Math.floor(drift.length/2)] : null}); }
            };
            requestAnimationFrame(tick);
        })""", [w for l in data["lines"] for w in l["words"]])
        m1 = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
        cpu = {k + "_ms_per_s": round((m1[k] - m0[k]) * 1000 / 8, 1)
               for k in ("TaskDuration", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration")}
        # Voix-guide activée en pleine lecture : doit démarrer calée sur l'instrumental.
        page.evaluate("""() => { const r=document.querySelector('.guide input');
            const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
            set.call(r, '0.5'); r.dispatchEvent(new Event('input',{bubbles:true})); }""")
        guide = page.evaluate("""() => new Promise(res => setTimeout(() => {
            const a=document.querySelectorAll('audio'); const d=[];
            const t0=performance.now();
            const tick=()=>{ if (a[1] && !a[1].paused) d.push(Math.abs(a[1].currentTime-a[0].currentTime));
              if (performance.now()-t0<3000) requestAnimationFrame(tick);
              else res({guide_audio_elements: a.length, guide_playing: !!a[1] && !a[1].paused,
                        guide_drift_med: d.length? d.sort((x,y)=>x-y)[d.length>>1] : null,
                        guide_drift_max: d.length? Math.max(...d): null}); };
            requestAnimationFrame(tick); }, 1500))""")
        stats.update(guide)
        total_bytes = received["bytes"]
        results[slug] = {
            "click_to_player_s": round(t_player, 3),
            "click_to_first_sound_s": round(t_sound, 3),
            "bytes_before_first_sound_MB": round(bytes_before_sound / 1e6, 2),
            "seek_ok": seek_ok, "seek_target": seek_target, "pos_after_seek": round(pos_after_seek, 2),
            "seek_latency_s": round(seek_lat, 3) if seek_lat else None,
            "total_MB_downloaded": round(total_bytes / 1e6, 2),
            **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()},
            **cpu,
            "js_errors": errors[:3],
        }
        ctx.close()
    browser.close()
httpd.shutdown()
print(json.dumps({"label": label, "throttle_mbps": throttle, "cpu_throttle": cpu_rate, "results": results}, indent=1, ensure_ascii=False))
