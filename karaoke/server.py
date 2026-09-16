"""Petit serveur local (stdlib) : sert l'app web + la bibliothèque, et permet
d'enregistrer des corrections de synchro depuis l'éditeur du lecteur.

- GET /                -> app web (web/dist)
- GET /library/...     -> fichiers de la bibliothèque (audio, json) EN DIRECT
- POST /api/save/<slug>-> réécrit karaoke.json + lyrics.lrc + index.json
- GET  /api/music?path=… -> parcourt la musique (dossiers + fichiers audio)
- GET  /api/jobs        -> file de traitement (progression)
- POST /api/jobs        -> ajoute des morceaux/dossiers à traiter {paths, language}
- DELETE /api/jobs/<id> -> retire un morceau encore en attente
- POST /api/jobs/clear  -> efface les traitements terminés

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
import os
import json
import mimetypes
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, lrc
from .jobs import AUDIO_EXTS, JobQueue, expand_audio
from .pipeline import _update_index
from .transcribe import Line, Word
from .utils import atomic_write_text

# Utilisateurs Windows « système » à ignorer pour les dossiers Musique par défaut.
_WIN_SYSTEM_USERS = {"default", "default user", "public", "all users"}


def default_music_roots() -> list[Path]:
    """~/Music et les dossiers Musique Windows (WSL : /mnt/c/Users/<nom>/Music)."""
    roots = [Path.home() / "Music", Path.home() / "Musique"]
    users = Path("/mnt/c/Users")
    if users.is_dir():
        try:
            roots += [u / "Music" for u in sorted(users.iterdir())
                      if u.name.lower() not in _WIN_SYSTEM_USERS]
        except OSError:
            pass
    def usable(r: Path) -> bool:
        try:
            return r.is_dir() and os.access(r, os.R_OK | os.X_OK)
        except OSError:  # comptes Windows inaccessibles (WsiAccount…)
            return False

    return [r for r in roots if usable(r)]


def list_music(roots: list[Path], rel: str | None) -> dict:
    """Contenu d'un dossier de musique, limité aux racines autorisées."""
    if not rel:
        return {"path": None, "parent": None,
                "dirs": [{"name": str(r), "path": str(r)} for r in roots], "files": []}
    target = Path(rel)
    root = next((r for r in roots if _within(r, target)), None)
    if root is None or not target.is_dir():
        raise PermissionError("dossier hors des racines musicales")
    dirs, files = [], []
    with os.scandir(target) as it:
        for e in it:
            if e.name.startswith((".", "$")):
                continue
            try:
                if e.is_dir():
                    dirs.append({"name": e.name, "path": str(target / e.name)})
                elif e.is_file() and Path(e.name).suffix.lower() in AUDIO_EXTS:
                    files.append({"name": e.name, "path": str(target / e.name)})
            except OSError:
                continue
    key = lambda d: d["name"].lower()
    parent = None if target.resolve() == root.resolve() else str(target.parent)
    return {"path": str(target), "parent": parent,
            "dirs": sorted(dirs, key=key), "files": sorted(files, key=key)}


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


def make_handler(app_root: Path, lib_root: Path, music_roots: list[Path] | None = None,
                 jobs: JobQueue | None = None):
    music_roots = music_roots or []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # keep-alive : pas une connexion TCP par requête

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(url.path)
            if path == "/api/music":
                rel = urllib.parse.parse_qs(url.query).get("path", [None])[0]
                try:
                    return self._json(200, {**list_music(music_roots, rel), "roots": [str(r) for r in music_roots]})
                except (PermissionError, OSError) as exc:
                    return self._json(403, {"error": str(exc)})
            if path == "/api/jobs":
                return self._json(200, {"jobs": jobs.snapshot() if jobs else [], "enabled": jobs is not None})
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

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")

        def do_DELETE(self):
            path = urllib.parse.urlparse(self.path).path
            if jobs and path.startswith("/api/jobs/"):
                try:
                    ok = jobs.cancel(int(path.rsplit("/", 1)[1]))
                except ValueError:
                    ok = False
                return self._json(200 if ok else 409, {"ok": ok})
            return self._json(404, {"error": "route inconnue"})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/jobs/clear" and jobs:
                return self._json(200, {"cleared": jobs.clear_finished()})
            if path == "/api/jobs" and jobs:
                try:
                    payload = self._read_json()
                    wanted = [Path(p) for p in payload.get("paths", [])]
                    allowed = [p for p in wanted if any(_within(r, p) for r in music_roots)]
                    if len(allowed) != len(wanted):
                        return self._json(403, {"error": "chemin hors des racines musicales"})
                    files = expand_audio(allowed)
                    added = jobs.submit(files, payload.get("language"))
                except Exception as exc:
                    return self._json(400, {"error": str(exc)})
                return self._json(200, {"added": len(added), "found": len(files)})
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
            atomic_write_text(mf, json.dumps(data, ensure_ascii=False, indent=2))

            objs = [
                Line(l["start"], l["end"],
                     [Word(w["text"], w["start"], w["end"]) for w in l["words"]])
                for l in norm
            ]
            atomic_write_text(song_dir / "lyrics.lrc",
                          lrc.write_lrc(objs, data.get("title", ""), data.get("artist", "")))
            _update_index(lib_root)

        def log_message(self, *args):  # silencieux
            pass

    return Handler


def serve(port: int = 8765, app_root: Path | None = None, lib_root: Path | None = None,
          music_roots: list[Path] | None = None, device: str = "auto"):
    app_root = app_root or (config.PROJECT_ROOT / "web" / "dist")
    lib_root = lib_root or config.DEFAULT_LIBRARY_DIR
    lib_root.mkdir(parents=True, exist_ok=True)
    music_roots = [Path(r).expanduser() for r in music_roots] if music_roots else default_music_roots()
    if not (app_root / "index.html").is_file():
        raise RuntimeError(
            f"App web non construite ({app_root}). Lance d'abord : cd web && npm run build"
        )
    jobs = JobQueue(lib_root, device=device)
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app_root, lib_root, music_roots, jobs))
    httpd.daemon_threads = True
    print(f"🎤 Karaoké (avec éditeur) sur http://localhost:{port}  — Ctrl+C pour arrêter")
    print("   Musique parcourable : " + (", ".join(map(str, music_roots)) or "aucune (--music DOSSIER)"))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
