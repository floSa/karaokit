"""Petit serveur local (stdlib) : sert l'app web + la bibliothèque, et permet
d'enregistrer des corrections de synchro depuis l'éditeur du lecteur.

- GET /                -> app web (web/dist)
- GET /library/...     -> fichiers de la bibliothèque (audio, json) EN DIRECT
- POST /api/save/<slug>-> réécrit karaoke.json + lyrics.lrc + index.json

Aucune dépendance externe : http.server de la bibliothèque standard.

Service des fichiers pensé pour l'audio :
- **HTTP Range (206)** : indispensable au lecteur — sans lui, Chrome ne peut pas
  se déplacer dans un MP3 (la lecture repart de 0 au moindre seek).
- envoi **en flux** par blocs (pas de lecture du fichier entier en mémoire) ;
- HTTP/1.1 keep-alive, validation `ETag`/`Last-Modified` (réponses 304) et
  cache long pour les assets Vite fingerprintés.
"""

from __future__ import annotations

import email.utils
import json
import mimetypes
import re
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


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 256 * 1024


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | bool:
    """Interprète un en-tête `Range` simple.

    Renvoie (début, fin incluse), None si absent/ignoré (réponse 200 complète),
    ou False si la plage est non satisfaisable (416).
    """
    if not header:
        return None
    m = _RANGE.match(header.strip())
    if not m or (not m.group(1) and not m.group(2)):
        return None  # multi-plages ou syntaxe inconnue : on sert tout (autorisé par la RFC)
    if not m.group(1):  # suffixe : les N derniers octets
        length = int(m.group(2))
        if length == 0:
            return False
        return max(0, size - length), size - 1
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else size - 1
    if start >= size or end < start:
        return False
    return start, min(end, size - 1)


def make_handler(app_root: Path, lib_root: Path):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive : pas une connexion TCP par requête

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

        def do_HEAD(self):
            self.do_GET()

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
            st = fs.stat()
            size = st.st_size
            etag = f'"{st.st_mtime_ns:x}-{size:x}"'
            ctype = mimetypes.guess_type(str(fs))[0] or "application/octet-stream"

            # Les assets Vite ont un hash dans leur nom : cache long. Le reste
            # (json, audio régénérables) est revalidé à chaque fois (304 si inchangé).
            immutable = root == app_root and "/assets/" in fs.as_posix()
            cache = "public, max-age=31536000, immutable" if immutable else "no-cache"

            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", cache)
                self.send_header("Content-Length", "0")
                self._cors()
                return self.end_headers()

            rng = parse_range(self.headers.get("Range"), size)
            if rng is False:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self._cors()
                return self.end_headers()
            start, end = rng if rng else (0, size - 1)
            length = end - start + 1 if size else 0

            self.send_response(206 if rng else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if rng:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("ETag", etag)
            self.send_header("Last-Modified", email.utils.formatdate(st.st_mtime, usegmt=True))
            self.send_header("Cache-Control", cache)
            self._cors()
            self.end_headers()
            if self.command == "HEAD" or not length:
                return
            try:
                with fs.open("rb") as fh:
                    fh.seek(start)
                    remaining = length
                    while remaining:
                        block = fh.read(min(_CHUNK, remaining))
                        if not block:
                            break
                        self.wfile.write(block)
                        remaining -= len(block)
            except (BrokenPipeError, ConnectionResetError):
                # Normal : le navigateur annule une requête audio quand on seek.
                self.close_connection = True

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
            _atomic_write(mf, json.dumps(data, ensure_ascii=False, indent=2))

            objs = [
                Line(l["start"], l["end"],
                     [Word(w["text"], w["start"], w["end"]) for w in l["words"]])
                for l in norm
            ]
            _atomic_write(song_dir / "lyrics.lrc",
                          lrc.write_lrc(objs, data.get("title", ""), data.get("artist", "")))
            _update_index(lib_root)

        def log_message(self, *args):  # silencieux
            pass

    return Handler


def _atomic_write(path: Path, text: str) -> None:
    """Écrit via un fichier temporaire : un lecteur ne voit jamais un JSON à moitié écrit."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def serve(port: int = 8765, app_root: Path | None = None, lib_root: Path | None = None):
    app_root = app_root or (config.PROJECT_ROOT / "web" / "dist")
    lib_root = lib_root or config.DEFAULT_LIBRARY_DIR
    if not (app_root / "index.html").is_file():
        raise RuntimeError(
            f"App web non construite ({app_root}). Lance d'abord : cd web && npm run build"
        )
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app_root, lib_root))
    httpd.daemon_threads = True
    print(f"🎤 Karaoké (avec éditeur) sur http://localhost:{port}  — Ctrl+C pour arrêter")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
