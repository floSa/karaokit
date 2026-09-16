"""Lecture des métadonnées d'un fichier audio (titre / artiste).

On lit d'abord les tags embarqués via ffprobe (fiable), puis on retombe sur des
heuristiques basées sur le nom de fichier et l'arborescence
(.../Artiste/Album/NN - Titre.flac).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .utils import ffprobe_bin

# Dossiers « génériques » qui ne sont pas des noms d'artiste.
_GENERIC_DIRS = {
    "music", "musique", "albums", "album", "downloads", "téléchargements",
    "desktop", "bureau", "documents", "flac", "mp3", "songs", "chansons",
}


def _read_tags(path: Path) -> dict[str, str]:
    """Renvoie les tags (clés en minuscules) via ffprobe, ou {} si indisponible."""
    try:
        out = subprocess.run(
            [ffprobe_bin(), "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            check=True, stdout=subprocess.PIPE,
        ).stdout
        tags = json.loads(out).get("format", {}).get("tags", {})
        return {k.lower(): v for k, v in tags.items()}
    except Exception:
        return {}


def _title_from_name(path: Path) -> str:
    """'01 - Revenons au début' -> 'Revenons au début' (retire le n° de piste)."""
    stem = path.stem
    stem = re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", stem)  # '01 - ', '01. ', '1) '
    if " - " in stem:  # 'Artiste - Titre'
        stem = stem.split(" - ", 1)[1]
    return stem.strip()


def _artist_from_path(path: Path) -> str:
    """Devine l'artiste depuis l'arborescence : .../Artiste/Album/piste.flac."""
    parts = path.resolve().parts
    # On remonte : parent = album, grand-parent = artiste (si non générique).
    if len(parts) >= 3:
        grandparent = parts[-3]
        if grandparent.lower() not in _GENERIC_DIRS:
            return grandparent
    return ""


def read_metadata(path: Path) -> tuple[str, str]:
    """Renvoie (titre, artiste) : tags embarqués d'abord, sinon heuristiques."""
    tags = _read_tags(path)
    title = tags.get("title") or _title_from_name(path)
    artist = (
        tags.get("artist")
        or tags.get("album_artist")
        or _artist_from_path(path)
    )
    return title.strip(), artist.strip()
