"""Playlist de lecture partagée + index de recherche de la musique de l'ordinateur.

Playlist : une seule liste ordonnée, enregistrée dans `library/playlist.json`
(elle survit au rechargement de la page et au redémarrage du serveur). Un élément
désigne soit un morceau de la bibliothèque (`slug`), soit un fichier de
l'ordinateur (`path`) : ce dernier est envoyé à la file de traitement et reçoit
son `slug` dès qu'il est prêt.

Index : parcours des dossiers de musique en tâche de fond (~3 s pour 3 400
morceaux via WSL), rafraîchi à la demande ou quand il a plus de 10 minutes.
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
import unicodedata
from pathlib import Path

from .jobs import AUDIO_EXTS, JobQueue
from .utils import atomic_write_text

INDEX_MAX_AGE = 600  # s


def fold(text: str) -> str:
    """Minuscules sans accents, pour une recherche tolérante ('Sébastien' ~ 'sebastien')."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def matches(query: str, haystack: str) -> bool:
    """Tous les mots de la requête apparaissent dans le texte (ordre libre)."""
    hay = fold(haystack)
    return all(word in hay for word in fold(query).split())


class MusicIndex:
    def __init__(self, roots: list[Path]):
        self.roots = roots
        self._files: list[dict] = []
        self._built = 0.0
        self._lock = threading.Lock()
        self._scanning = False

    def refresh(self, wait: bool = False) -> None:
        with self._lock:
            if self._scanning:
                return
            self._scanning = True
        thread = threading.Thread(target=self._scan, name="music-index", daemon=True)
        thread.start()
        if wait:
            thread.join()

    def _scan(self) -> None:
        files = []
        try:
            for root in self.roots:
                for current, dirs, names in os.walk(root):
                    dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$")))
                    rel_dir = os.path.relpath(current, root)
                    for name in names:
                        if os.path.splitext(name)[1].lower() in AUDIO_EXTS:
                            files.append({
                                "path": os.path.join(current, name),
                                "name": name,
                                "folder": "" if rel_dir == "." else rel_dir,
                            })
        finally:
            with self._lock:
                if files or not self._files:
                    self._files = files
                self._built = time.time()
                self._scanning = False

    def status(self) -> dict:
        with self._lock:
            return {"count": len(self._files), "scanning": self._scanning, "built": self._built}

    def search(self, query: str, limit: int = 60) -> list[dict]:
        if time.time() - self._built > INDEX_MAX_AGE:
            self.refresh()
        with self._lock:
            files = self._files
        out = []
        for f in files:
            if matches(query, f"{f['folder']} {f['name']}"):
                out.append(f)
                if len(out) >= limit:
                    break
        return out


class Playlist:
    def __init__(self, library_dir: Path, jobs: JobQueue):
        self.file = library_dir / "playlist.json"
        self.library_dir = library_dir
        self.jobs = jobs
        self._lock = threading.Lock()
        self._items: list[dict] = []
        if self.file.is_file():
            try:
                self._items = json.loads(self.file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._items = []
        start = max((it["id"] for it in self._items), default=0) + 1
        self._ids = itertools.count(start)
        # Éléments non terminés lors d'un arrêt du serveur : on relance leur traitement.
        pending = [Path(it["path"]) for it in self._items if it.get("path") and not it.get("slug")]
        if pending:
            self.jobs.submit([p for p in pending if p.is_file()])

    def _save(self) -> None:
        atomic_write_text(self.file, json.dumps(self._items, ensure_ascii=False, indent=2))

    def _library_entry(self, slug: str) -> dict | None:
        manifest = self.library_dir / slug / "karaoke.json"
        if not manifest.is_file():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return {"title": data.get("title") or slug, "artist": data.get("artist") or ""}

    def add(self, slugs: list[str], files: list[Path], language: str | None = None) -> int:
        with self._lock:
            added = 0
            for slug in slugs:
                entry = self._library_entry(slug)
                if entry:
                    self._items.append({"id": next(self._ids), "slug": slug, **entry})
                    added += 1
            for f in files:
                self._items.append({"id": next(self._ids), "path": str(f), "slug": None,
                                    "title": f.stem, "artist": ""})
                added += 1
            self._save()
        if files:
            self.jobs.submit(files, language)
        return added

    def remove(self, item_id: int) -> bool:
        with self._lock:
            item = next((it for it in self._items if it["id"] == item_id), None)
            if not item:
                return False
            self._items.remove(item)
            still_wanted = item.get("path") and any(it.get("path") == item["path"] for it in self._items)
            self._save()
        if item.get("path") and not item.get("slug") and not still_wanted:
            for job in self.jobs.snapshot():
                if job["path"] == item["path"] and job["status"] == "queued":
                    self.jobs.cancel(job["id"])
        return True

    def reorder(self, ids: list[int]) -> None:
        with self._lock:
            by_id = {it["id"]: it for it in self._items}
            ordered = [by_id.pop(i) for i in ids if i in by_id]
            self._items = ordered + list(by_id.values())  # éléments inconnus du client : gardés à la fin
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._save()

    def snapshot(self) -> list[dict]:
        """Éléments + état de préparation (prêt, étape de traitement, erreur)."""
        jobs_by_path: dict[str, dict] = {}
        for job in self.jobs.snapshot():  # le plus récent l'emporte
            jobs_by_path[job["path"]] = job
        out, changed = [], False
        with self._lock:
            for it in self._items:
                view = dict(it)
                job = jobs_by_path.get(it.get("path") or "")
                if not it.get("slug") and job and job["status"] in ("done", "skipped") and job.get("slug"):
                    # Traitement terminé : on mémorise le morceau de la bibliothèque.
                    it.update(slug=job["slug"], title=job.get("title") or it["title"],
                              artist=job.get("artist") or "")
                    view.update(it)
                    changed = True
                if it.get("slug") and self._library_entry(it["slug"]):
                    view["state"], view["label"] = "ready", "prêt"
                elif job:
                    view["state"] = {"queued": "queued", "running": "processing"}.get(job["status"], job["status"])
                    view["label"] = job["error"] if job["status"] == "error" else job["stage_label"]
                    if job["status"] == "running" and job.get("started"):
                        view["elapsed"] = round(time.time() - job["started"])
                    if job.get("title"):
                        view["title"], view["artist"] = job["title"], job.get("artist") or ""
                else:
                    view["state"], view["label"] = "missing", "introuvable"
                out.append(view)
            if changed:
                self._save()
        return out
