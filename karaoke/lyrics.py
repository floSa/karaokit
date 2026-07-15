"""Brique 2 — Récupération des paroles depuis des sources en ligne.

On tente d'abord le raccourci en or : un LRC déjà synchronisé (LRCLIB, Musixmatch…)
via la lib `syncedlyrics`. Si trouvé, les étapes 2 ET 3 sont réglées d'un coup.
Sinon on récupère au moins le texte brut, qui servira de référence à l'alignement.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LyricsResult:
    text: str            # paroles (brut ou contenu LRC)
    synced: bool         # True si c'est du LRC déjà horodaté
    source: str          # d'où ça vient (info)


def _looks_like_lrc(text: str) -> bool:
    """Un contenu LRC contient des tags de temps '[mm:ss.xx]'."""
    import re

    return bool(re.search(r"\[\d{1,2}:\d{2}(\.\d{1,3})?\]", text))


def fetch_lyrics(title: str, artist: str) -> LyricsResult | None:
    """Cherche les paroles en ligne. Renvoie None si rien trouvé."""
    try:
        import syncedlyrics
    except ImportError as exc:
        raise RuntimeError(
            "La lib 'syncedlyrics' n'est pas installée (voir requirements)."
        ) from exc

    query = f"{title} {artist}".strip()

    # 1) On tente d'abord du synchronisé (LRC)
    synced = None
    try:
        synced = syncedlyrics.search(query, synced_only=True)
    except Exception:
        synced = None

    if synced and _looks_like_lrc(synced):
        return LyricsResult(text=synced, synced=True, source="en ligne (LRC synchronisé)")

    # 2) Sinon, on récupère au moins le texte brut
    plain = None
    try:
        plain = syncedlyrics.search(query, plain_only=True)
    except Exception:
        plain = None

    if plain and plain.strip():
        return LyricsResult(text=plain.strip(), synced=False, source="en ligne (texte brut)")

    return None
