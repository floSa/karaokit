"""Brique 2 (niveau 2) — Alignement forcé d'un TEXTE connu sur la voix isolée.

On ne *devine* pas les paroles : on les a déjà (récupérées en ligne). On se
contente de poser les timecodes mot-à-mot dessus, en analysant la piste voix,
via le moteur de forced alignment **MMS_FA** intégré à torchaudio (modèle
wav2vec2 multilingue de Meta). 100 % local, wheel précompilé, aucun compilateur.

Entrée : voix isolée + texte propre. Sortie : lignes/mots horodatés.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from pathlib import Path

from .config import Profile
from .transcribe import Line, Word
from .utils import ffmpeg_bin

_SAMPLE_RATE = 16000  # imposé par le modèle MMS_FA


def _normalize(word: str) -> str:
    """Réduit un mot au jeu de caractères du modèle : [a-z'] sans accents.

    Sert UNIQUEMENT à l'alignement (le mot affiché reste l'original). Ex :
    'Été' -> 'ete', "l'amour" -> "l'amour", '#1' -> ''.
    """
    word = unicodedata.normalize("NFKD", word)
    word = word.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z']", "", word)


def _load_vocals_16k(vocals: Path):
    """Décode la voix en mono 16 kHz float32 via ffmpeg (robuste, tout format)."""
    import numpy as np
    import torch

    cmd = [
        ffmpeg_bin(), "-i", str(vocals),
        "-f", "s16le", "-ac", "1", "-ar", str(_SAMPLE_RATE),
        "-loglevel", "error", "-",
    ]
    raw = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return torch.from_numpy(samples).unsqueeze(0)  # forme (1, N)


def align_lyrics(
    vocals: Path,
    text: str,
    profile: Profile,
    language: str | None = None,  # gardé pour cohérence d'API (MMS_FA est multilingue)
) -> list[Line]:
    """Aligne `text` sur la voix `vocals`. Renvoie des lignes horodatées.

    Les sauts de ligne du texte définissent les lignes du karaoké ; chaque mot
    reçoit un (start, end) issu de l'alignement.
    """
    import torch
    from torchaudio.pipelines import MMS_FA as bundle

    device = profile.device

    # 1) Découpage du texte : lignes -> mots (originaux conservés pour l'affichage).
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    line_words = [ln.split() for ln in raw_lines]
    flat_words = [w for lw in line_words for w in lw]
    if not flat_words:
        return []

    # Mots normalisés pour l'alignement + index des mots réellement alignables.
    normalized = [_normalize(w) for w in flat_words]
    transcript = [n for n in normalized if n]
    if not transcript:
        return []

    print(f"  [MMS_FA] forced alignment device={device} — {len(transcript)} mots …", flush=True)

    # 2) Modèle + audio
    model = bundle.get_model(with_star=False).to(device).eval()
    tokenizer = bundle.get_tokenizer()
    aligner = bundle.get_aligner()

    waveform = _load_vocals_16k(vocals).to(device)
    with torch.inference_mode():
        emission, _ = model(waveform)
    num_frames = emission.size(1)
    duration = waveform.size(1) / _SAMPLE_RATE  # secondes

    # 3) Alignement : un groupe de token-spans par mot du transcript.
    token_spans = aligner(emission[0], tokenizer(transcript))

    def frame_to_sec(frame: float) -> float:
        return float(frame) / num_frames * duration

    times: list[tuple[float, float]] = []
    for spans in token_spans:
        start = frame_to_sec(spans[0].start)
        end = frame_to_sec(spans[-1].end)
        times.append((start, end))

    # 4) On réassocie les timecodes aux mots ORIGINAUX (y compris ceux non
    #    alignables, ex. '#1' : ils héritent du temps du voisin).
    return _rebuild_lines(line_words, normalized, times)


def _rebuild_lines(
    line_words: list[list[str]],
    normalized: list[str],
    times: list[tuple[float, float]],
) -> list[Line]:
    """Recolle les timecodes (dans l'ordre des mots alignables) sur les lignes."""
    lines: list[Line] = []
    ti = 0          # curseur dans `times` (mots alignables seulement)
    ni = 0          # curseur global dans `normalized`
    last_end = 0.0

    for words in line_words:
        out_words: list[Word] = []
        for token in words:
            if normalized[ni]:  # mot alignable -> a un timecode
                start, end = times[ti] if ti < len(times) else (last_end, last_end)
                ti += 1
                last_end = end
                out_words.append(Word(text=token, start=start, end=end))
            else:               # mot non alignable (chiffre, ponctuation) -> voisin
                out_words.append(Word(text=token, start=last_end, end=last_end))
            ni += 1
        if out_words:
            lines.append(Line(start=out_words[0].start, end=out_words[-1].end, words=out_words))
    return lines
