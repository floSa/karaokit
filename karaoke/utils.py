"""Petits utilitaires partagés."""

from __future__ import annotations

import re
import shutil
import subprocess
import unicodedata
from pathlib import Path


def ffmpeg_bin() -> str:
    """Localise l'exécutable ffmpeg : PATH, sinon scripts/bin/ffmpeg (bootstrap)."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    local = Path(__file__).resolve().parent.parent / "scripts" / "bin" / "ffmpeg"
    if local.exists():
        return str(local)
    raise RuntimeError(
        "ffmpeg introuvable. Lance scripts/bootstrap.sh ou ajoute-le au PATH "
        '(export PATH="$PWD/scripts/bin:$PATH").'
    )


def preload_cuda_libs() -> None:
    """Rend cuBLAS/cuDNN (wheels pip `nvidia-*`) visibles pour ctranslate2.

    torch charge ces bibliothèques par chemin absolu, mais ctranslate2
    (faster-whisper / WhisperX) les cherche par nom (`libcublas.so.12`) et échoue
    avec « Library libcublas.so.12 is not found » si elles ne sont pas dans
    LD_LIBRARY_PATH. On les pré-charge en RTLD_GLOBAL : le dlopen par nom les
    retrouve alors. Sans effet hors Linux ou sans ces paquets.
    """
    import ctypes
    import glob
    import os

    try:
        import nvidia.cublas
        import nvidia.cudnn
    except ImportError:
        return
    for pkg in (nvidia.cublas, nvidia.cudnn):
        for lib_dir in pkg.__path__:
            for lib in sorted(glob.glob(os.path.join(lib_dir, "lib", "lib*.so.*"))):
                try:
                    ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


def slugify(value: str) -> str:
    """Transforme 'Daft Punk — Get Lucky' en 'daft-punk-get-lucky'."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    value = re.sub(r"[-\s]+", "-", value)
    return value or "morceau"


def format_lrc_time(seconds: float) -> str:
    """Convertit des secondes en timestamp LRC '[mm:ss.xx]'."""
    if seconds < 0:
        seconds = 0.0
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02d}:{secs:05.2f}"


def ffprobe_bin() -> str:
    """ffprobe est livré à côté de ffmpeg (même dossier)."""
    probe = Path(ffmpeg_bin()).with_name("ffprobe")
    return str(probe) if probe.exists() else "ffprobe"


def probe_duration(path: Path) -> float | None:
    """Durée (s) d'un fichier audio/vidéo, ou None si illisible."""
    try:
        out = subprocess.run(
            [ffprobe_bin(), "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            check=True, stdout=subprocess.PIPE,
        ).stdout.decode().strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def check_ffmpeg() -> None:
    """Vérifie que ffmpeg est accessible ; lève une erreur claire sinon."""
    subprocess.run(
        [ffmpeg_bin(), "-version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
