"""Brique 2 — Récupération des paroles depuis des sources en ligne.

Ordre de recherche :
1. **LRCLIB en direct** (`/api/get` puis `/api/search`) avec la **durée** du
   morceau : correspondance fiable (artiste + titre + durée à ±3 s), ~0,5 s.
   Un résultat trouvé ainsi est marqué `trusted=True`.
2. **syncedlyrics** (Musixmatch, Genius, NetEase…) en secours : couverture plus
   large mais recherche floue — le résultat peut être celui d'un AUTRE morceau.
   Il est donc marqué `trusted=False` et doit être vérifié contre l'audio
   (voir `verify.py`).

Les suffixes de titre parasites (« (Album Version) », « - Remastered 2011 »…)
sont retirés avant la recherche.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

LRCLIB = "https://lrclib.net/api"
_USER_AGENT = "Karaokit (https://github.com/floSa/karaokit)"
_DURATION_TOLERANCE = 3.0  # s

# Mentions de version sans incidence sur les paroles.
_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(album|single|radio|explicit|clean|remaster(ed)?|version|edit|"
    r"mono|stereo|deluxe|bonus|live at|feat\.?|ft\.?)\b[^\)\]]*[\)\]]"
    r"|\s+-\s+.*\b(remaster(ed)?|version|edit|mono|stereo)\b.*$",
    re.IGNORECASE,
)


@dataclass
class LyricsResult:
    text: str            # paroles (brut ou contenu LRC)
    synced: bool         # True si c'est du LRC déjà horodaté
    source: str          # d'où ça vient (info)
    trusted: bool = False  # correspondance vérifiée (durée) -> pas besoin de contrôle audio


def clean_title(title: str) -> str:
    """'SOS (Album Version)' -> 'SOS' ; 'Song - Remastered 2011' -> 'Song'."""
    cleaned = _NOISE.sub("", title).strip()
    return cleaned or title.strip()


def _looks_like_lrc(text: str) -> bool:
    """Un contenu LRC contient des tags de temps '[mm:ss.xx]'."""
    return bool(re.search(r"\[\d{1,2}:\d{2}(\.\d{1,3})?\]", text))


def _http_json(url: str, timeout: float = 6.0):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _pick(record: dict | None) -> LyricsResult | None:
    if not record or record.get("instrumental"):
        return None
    if record.get("syncedLyrics") and _looks_like_lrc(record["syncedLyrics"]):
        return LyricsResult(record["syncedLyrics"], True, "LRCLIB (LRC synchronisé)", trusted=True)
    if (record.get("plainLyrics") or "").strip():
        return LyricsResult(record["plainLyrics"].strip(), False, "LRCLIB (texte brut)", trusted=True)
    return None


def best_search_match(results: list[dict], duration: float | None) -> dict | None:
    """Choisit, parmi des résultats de recherche LRCLIB, celui dont la durée colle.

    Sans durée connue, on ne choisit rien : une recherche floue sans contrôle est
    exactement ce qui produit des paroles d'un autre morceau.
    """
    if duration is None:
        return None
    candidates = [
        r for r in results
        if r.get("duration") and abs(float(r["duration"]) - duration) <= _DURATION_TOLERANCE
        and (r.get("syncedLyrics") or r.get("plainLyrics"))
    ]
    # Préférence : synchronisé, puis durée la plus proche.
    candidates.sort(key=lambda r: (not r.get("syncedLyrics"), abs(float(r["duration"]) - duration)))
    return candidates[0] if candidates else None


def fetch_lrclib(title: str, artist: str, duration: float | None) -> LyricsResult | None:
    """Recherche directe LRCLIB (rapide et fiable grâce à la durée)."""
    if not artist or not title:
        return None
    params = {"track_name": title, "artist_name": artist}
    if duration:
        params["duration"] = str(round(duration))
    try:
        found = _pick(_http_json(f"{LRCLIB}/get?{urllib.parse.urlencode(params)}"))
        if found:
            return found
    except Exception:  # 404 (introuvable), réseau, serveur occupé…
        pass
    try:
        q = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
        return _pick(best_search_match(_http_json(f"{LRCLIB}/search?{q}"), duration))
    except Exception:
        return None


def fetch_syncedlyrics(title: str, artist: str) -> LyricsResult | None:
    """Recherche floue multi-fournisseurs (résultat NON garanti : à vérifier)."""
    try:
        import syncedlyrics
    except ImportError:
        return None

    query = f"{title} {artist}".strip()
    try:
        synced = syncedlyrics.search(query, synced_only=True)
    except Exception:
        synced = None
    if synced and _looks_like_lrc(synced):
        return LyricsResult(synced, True, "recherche floue (LRC synchronisé)")
    try:
        plain = syncedlyrics.search(query, plain_only=True)
    except Exception:
        plain = None
    if plain and plain.strip():
        return LyricsResult(plain.strip(), False, "recherche floue (texte brut)")
    return None


def fetch_lyrics(title: str, artist: str, duration: float | None = None) -> LyricsResult | None:
    """Cherche les paroles en ligne. Renvoie None si rien trouvé."""
    titles = [title]
    if clean_title(title) != title:
        titles.insert(0, clean_title(title))
    for t in titles:
        found = fetch_lrclib(t, artist, duration)
        if found:
            return found
    return fetch_syncedlyrics(titles[0], artist)
