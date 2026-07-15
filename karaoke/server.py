"""Petit serveur local (stdlib) : sert l'app web + la bibliothèque, et permet
d'enregistrer des corrections de synchro depuis l'éditeur du lecteur.

- GET /                -> app web (web/dist)
- GET /library/...     -> fichiers de la bibliothèque (audio, json) EN DIRECT
- POST /api/save/<slug>-> réécrit karaoke.json + lyrics.lrc + index.json

Aucune dépendance externe : http.server de la bibliothèque standard.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, lrc
from .pipeline import _update_index
from .transcribe import Line, Word


def _within(root: Path, target: Path) -> bool:
    """Garde-fou anti-traversée de chemin."""
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def make_handler(app_root: Path, lib_root: Path):
    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            path = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
            if path.startswith("/library/"):
                self._send_file(lib_root, lib_root / path[len("/library/"):])
            else:
                rel = path.lstrip("/") or "index.html"
                fs = app_root / rel
                if not fs.is_file():
                    fs = app_root / "index.html"  # fallback SPA
                self._send_file(app_root, fs)

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if not path.startswith("/api/save/"):
                return self._json(404, {"error": "route inconnue"})
            slug = path[len("/api/save/"):].strip("/")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                self._save(slug, payload)
            except Exception as exc:
                return self._json(400, {"error": str(exc)})
            return self._json(200, {"ok": True, "slug": slug})

        # --- helpers ---
        def _send_file(self, root: Path, fs: Path):
            if not _within(root, fs) or not fs.is_file():
                return self._json(404, {"error": "introuvable"})
            data = fs.read_bytes()
            ctype = mimetypes.guess_type(str(fs))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code: int, obj: dict):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _save(self, slug: str, payload: dict):
            song_dir = lib_root / slug
            mf = song_dir / "karaoke.json"
            if not _within(lib_root, mf) or not mf.is_file():
                raise FileNotFoundError(f"morceau inconnu : {slug}")
            data = json.loads(mf.read_text(encoding="utf-8"))

            lines_in = payload.get("lines")
            if not isinstance(lines_in, list):
                raise ValueError("payload.lines manquant ou invalide")

            norm = []
            for l in lines_in:
                words = [
                    {"text": str(w["text"]), "start": float(w["start"]), "end": float(w["end"])}
                    for w in l["words"]
                ]
                if not words:
                    continue
                norm.append({"start": float(l["start"]), "end": float(l["end"]), "words": words})

            data["lines"] = norm
            data["wordLevel"] = any(len(l["words"]) > 1 for l in norm)
            data["edited"] = True
            mf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            objs = [
                Line(l["start"], l["end"],
                     [Word(w["text"], w["start"], w["end"]) for w in l["words"]])
                for l in norm
            ]
            (song_dir / "lyrics.lrc").write_text(
                lrc.write_lrc(objs, data.get("title", ""), data.get("artist", "")),
                encoding="utf-8",
            )
            _update_index(lib_root)

        def log_message(self, *args):  # silencieux
            pass

    return Handler


def serve(port: int = 8765, app_root: Path | None = None, lib_root: Path | None = None):
    app_root = app_root or (config.PROJECT_ROOT / "web" / "dist")
    lib_root = lib_root or config.DEFAULT_LIBRARY_DIR
    if not (app_root / "index.html").is_file():
        raise RuntimeError(
            f"App web non construite ({app_root}). Lance d'abord : cd web && npm run build"
        )
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app_root, lib_root))
    print(f"🎤 Karaoké (avec éditeur) sur http://localhost:{port}  — Ctrl+C pour arrêter")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
