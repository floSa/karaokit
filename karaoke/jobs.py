"""File d'attente de traitement pilotée depuis l'app web.

L'utilisateur choisit des morceaux (ou des albums entiers) dans sa musique ; ils
sont traités un par un dans un thread de fond du serveur, qui garde les modèles
chargés d'un morceau à l'autre. L'app web interroge `snapshot()` pour afficher
la progression (étape en cours, durée, erreur éventuelle).

L'état est en mémoire : un redémarrage du serveur vide la file (les morceaux déjà
traités restent dans la bibliothèque).
"""

from __future__ import annotations

import itertools
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

AUDIO_EXTS = {".flac", ".mp3", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".wma"}

# Libellés des étapes, dans l'ordre du pipeline (affichés tels quels par l'app web).
STAGES = {
    "queued": "en attente",
    "separation": "séparation voix / instrumental",
    "lyrics": "recherche des paroles",
    "check": "vérification des paroles",
    "sync": "synchronisation mot-à-mot",
    "writing": "écriture",
}


@dataclass
class Job:
    id: int
    path: str
    name: str
    language: str | None = None
    status: str = "queued"          # queued | running | done | skipped | error | cancelled
    stage: str = "queued"
    stage_label: str = STAGES["queued"]
    slug: str | None = None
    title: str | None = None
    artist: str | None = None
    lyrics_source: str | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None


def expand_audio(paths: list[Path]) -> list[Path]:
    """Fichiers audio désignés par une sélection (un dossier = tous ses morceaux)."""
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXTS))
        elif p.is_file() and p.suffix.lower() in AUDIO_EXTS:
            out.append(p)
    return out


class JobQueue:
    def __init__(self, library_dir: Path, device: str = "auto"):
        self.library_dir = library_dir
        self.device = device
        self._jobs: dict[int, Job] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # --- API appelée par le serveur (threads HTTP) --------------------------
    def submit(self, files: list[Path], language: str | None = None) -> list[Job]:
        added = []
        with self._lock:
            pending = {j.path for j in self._jobs.values() if j.status in ("queued", "running")}
            for f in files:
                key = str(f)
                if key in pending:  # déjà dans la file : pas de doublon
                    continue
                job = Job(id=next(self._ids), path=key, name=f.stem, language=language or None)
                self._jobs[job.id] = job
                pending.add(key)
                added.append(job)
            if added and self._thread is None:
                self._thread = threading.Thread(target=self._worker, name="karaoke-jobs", daemon=True)
                self._thread.start()
        self._wake.set()
        return added

    def cancel(self, job_id: int) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status == "queued":
                job.status, job.finished = "cancelled", time.time()
                return True
            return False

    def clear_finished(self) -> int:
        with self._lock:
            ended = [i for i, j in self._jobs.items() if j.status not in ("queued", "running")]
            for i in ended:
                del self._jobs[i]
            return len(ended)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [asdict(j) for j in self._jobs.values()]

    # --- Thread de fond --------------------------------------------------------
    def _next(self) -> Job | None:
        with self._lock:
            for job in self._jobs.values():
                if job.status == "queued":
                    job.status, job.started = "running", time.time()
                    return job
        return None

    def _set(self, job: Job, **fields) -> None:
        with self._lock:
            for k, v in fields.items():
                setattr(job, k, v)

    def _worker(self) -> None:
        profile = None
        while True:
            self._wake.clear()  # AVANT de chercher : un ajout concurrent ne peut pas être manqué
            job = self._next()
            if job is None:
                if not self._wake.wait(timeout=60):
                    with self._lock:  # inactif : on s'arrête, relancé au prochain ajout
                        if not any(j.status == "queued" for j in self._jobs.values()):
                            self._thread = None
                            return
                continue
            try:
                # Import tardif : torch & co ne sont chargés qu'au premier traitement.
                from .config import build_profile, detect_device
                from .pipeline import build

                if profile is None:
                    profile = build_profile(detect_device(self.device))

                def progress(stage: str, **info) -> None:
                    self._set(job, stage=stage, stage_label=STAGES.get(stage, stage), **info)

                song_dir, skipped = build(
                    Path(job.path), self.library_dir, profile,
                    language=job.language, progress=progress, return_skipped=True,
                )
                data = json.loads((song_dir / "karaoke.json").read_text(encoding="utf-8"))
                self._set(job, status="skipped" if skipped else "done", stage="done",
                          stage_label="déjà dans la bibliothèque" if skipped else "prêt à chanter",
                          slug=data.get("slug"), title=data.get("title"), artist=data.get("artist"),
                          lyrics_source=data.get("lyrics_source"), finished=time.time())
            except Exception as exc:  # un morceau en échec ne bloque pas la file
                self._set(job, status="error", stage="error", stage_label="échec",
                          error=str(exc) or exc.__class__.__name__, finished=time.time())
