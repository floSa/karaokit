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


def slugify(value: str) -> str:
    """Transforme 'Daft Punk — Get Lucky' en 'daft-punk-get-lucky'."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    value = re.sub(r"[-\s]+", "-", value)
    return value or "morceau"


def guess_title_artist(path: Path) -> tuple[str, str]:
    """Devine (titre, artiste) depuis le nom de fichier 'Artiste - Titre.flac'.

    Renvoie (titre, artiste) ; artiste peut être vide si non déterminable.
    """
    stem = path.stem
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return title.strip(), artist.strip()
    return stem.strip(), ""


def format_lrc_time(seconds: float) -> str:
    """Convertit des secondes en timestamp LRC '[mm:ss.xx]'."""
    if seconds < 0:
        seconds = 0.0
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes:02d}:{secs:05.2f}"


def check_ffmpeg() -> None:
    """Vérifie que ffmpeg est accessible ; lève une erreur claire sinon."""
    subprocess.run(
        [ffmpeg_bin(), "-version"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
