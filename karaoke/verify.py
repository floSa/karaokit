"""Contrôle « ces paroles sont-elles bien celles du morceau ? ».

Une recherche floue (syncedlyrics) peut renvoyer les paroles d'un autre titre,
et l'alignement forcé les posera quand même sur la voix sans broncher (le score
CTC ne discrimine pas). On transcrit donc rapidement la voix isolée (Whisper)
et on mesure la part des **paires de mots consécutifs** entendues qui figurent
dans les paroles candidates. Les mots isolés ne suffisent pas (« love », « you »…
sont partout) ; les bigrammes, si.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .config import Profile
from .utils import preload_cuda_libs

# On arrête la transcription dès qu'on a entendu assez de mots pour trancher :
# pas besoin de transcrire tout le morceau.
_ENOUGH_WORDS = 60

# En dessous, les paroles sont jugées étrangères au morceau. Mesuré sur de vrais
# morceaux (Whisper small) : paroles correctes 0,28 – 0,78 ; autre morceau ≤ 0,02.
MIN_OVERLAP = 0.10

_MODEL = {}


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"\[[^\]]*\]|<[^>]*>", " ", text)  # tags LRC
    return [w for w in re.findall(r"[a-z]+", text) if len(w) >= 3]


def _bigrams(words: list[str]) -> list[tuple[str, str]]:
    return list(zip(words, words[1:]))


def overlap(transcript: str, lyrics: str) -> float | None:
    """Part des bigrammes transcrits présents dans les paroles. None si trop peu de mots."""
    heard = _bigrams(_tokens(transcript))
    if len(heard) < 8:  # quasi instrumental : pas assez d'indices pour juger
        return None
    known = set(_bigrams(_tokens(lyrics)))
    return sum(1 for b in heard if b in known) / len(heard)


def quick_transcript(vocals: Path, profile: Profile, language: str | None = None) -> tuple[str, str]:
    """Transcription rapide de la voix isolée. Renvoie (texte, langue détectée)."""
    preload_cuda_libs()
    from faster_whisper import WhisperModel

    key = (profile.verify_model, profile.device)
    if key not in _MODEL:
        _MODEL[key] = WhisperModel(profile.verify_model, device=profile.device,
                                   compute_type=profile.whisper_compute)
    segments, info = _MODEL[key].transcribe(
        str(vocals), language=language, beam_size=1, vad_filter=True,
        condition_on_previous_text=False,
    )
    texts, n_words = [], 0
    for seg in segments:  # générateur : le décodage s'arrête quand on sort de la boucle
        texts.append(seg.text)
        n_words += len(_tokens(seg.text))
        if n_words >= _ENOUGH_WORDS:
            break
    return " ".join(texts), info.language


def lyrics_match(vocals: Path, lyrics_text: str, profile: Profile,
                 language: str | None = None) -> tuple[bool, float | None, str]:
    """(paroles acceptées ?, score de recouvrement, langue détectée)."""
    transcript, lang = quick_transcript(vocals, profile, language)
    score = overlap(transcript, lyrics_text)
    return (score is None or score >= MIN_OVERLAP), score, lang
