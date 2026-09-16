"""Brique 2 (niveau 2) — Alignement forcé d'un TEXTE connu sur la voix isolée.

On ne *devine* pas les paroles : on les a déjà (récupérées en ligne). On se
contente de poser les timecodes mot-à-mot dessus, en analysant la piste voix,
via le moteur de forced alignment **MMS_FA** intégré à torchaudio (modèle
wav2vec2 multilingue de Meta). 100 % local, wheel précompilé, aucun compilateur.

Deux modes :
- `align_lyrics`   : texte brut, aligné sur tout le morceau d'un coup.
- `align_to_lines` : LRC ligne-à-ligne déjà synchronisé ; chaque ligne est
  alignée DANS SA FENÊTRE temporelle (début de ligne → début de la suivante).
  Aucune dérive possible, et on obtient le mot-à-mot pour presque rien.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
import warnings
from pathlib import Path

from .config import Profile
from .transcribe import Line, Word
from .utils import ffmpeg_bin

_SAMPLE_RATE = 16000  # imposé par le modèle MMS_FA
_MODEL: dict[str, object] = {}  # device -> modèle (chargé une fois par processus)

# Fenêtre autour d'une ligne LRC (s) : les LRC communautaires ont souvent
# quelques centaines de ms d'avance/retard.
_PAD_BEFORE = 0.6
_PAD_AFTER = 0.4
_MAX_LINE_SPAN = 12.0  # durée max d'une fenêtre (ex. dernière ligne, avant un solo)
_CHUNK_S, _CONTEXT_S = 30, 5  # découpage de l'audio pour le calcul des émissions
_HOP = 320  # échantillons par trame d'émission (20 ms à 16 kHz)


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


def _emission(vocals: Path, device: str):
    """Émissions CTC du modèle sur toute la voix. Renvoie (emission[T, C] sur CPU, secondes/frame).

    L'attention de wav2vec2 est quadratique en durée : un morceau de 7 min d'un
    seul bloc coûte ~13 s sur GPU. On traite des tranches de 30 s entourées de
    5 s de contexte (rognées ensuite) : coût linéaire, résultat équivalent.
    Le CTC lui-même tourne sur CPU (petits appels : plus rapide qu'aller-retour GPU).
    """
    import torch
    from torchaudio.pipelines import MMS_FA as bundle

    if device not in _MODEL:
        _MODEL[device] = bundle.get_model(with_star=False).to(device).eval()
    model = _MODEL[device]
    waveform = _load_vocals_16k(vocals)
    n = waveform.size(1)
    chunk, ctx = _CHUNK_S * _SAMPLE_RATE, _CONTEXT_S * _SAMPLE_RATE
    parts = []
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=device == "cuda"):
        for s0 in range(0, n, chunk):
            a, b = max(0, s0 - ctx), min(n, s0 + chunk + ctx)
            em, _ = model(waveform[:, a:b].to(device))
            em = em[0].float().cpu()
            first = (s0 - a) // _HOP  # trames de contexte à rogner (pas fixe de 20 ms)
            parts.append(em[first: first + (min(n, s0 + chunk) - s0) // _HOP])
    return torch.cat(parts), _HOP / _SAMPLE_RATE


def _force_align(emission, words: list[str]):
    """Alignement CTC de `words` (normalisés, non vides) sur `emission`. -> [(f0, f1)]."""
    from torchaudio.pipelines import MMS_FA as bundle

    with warnings.catch_warnings():  # dépréciation annoncée pour torchaudio 2.9 (on reste < 2.9)
        warnings.simplefilter("ignore")
        spans = bundle.get_aligner()(emission, bundle.get_tokenizer()(words))
    return [(s[0].start, s[-1].end) for s in spans]


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
    raw_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    line_words = [ln.split() for ln in raw_lines]
    normalized = [_normalize(w) for lw in line_words for w in lw]
    transcript = [n for n in normalized if n]
    if not transcript:
        return []

    print(f"  [MMS_FA] alignement device={profile.device} — {len(transcript)} mots …", flush=True)
    emission, spf = _emission(vocals, profile.device)
    times = [(f0 * spf, f1 * spf) for f0, f1 in _force_align(emission, transcript)]

    # On réassocie les timecodes aux mots ORIGINAUX (y compris ceux non
    # alignables, ex. '#1' : ils héritent du temps du voisin).
    return _rebuild_lines(line_words, normalized, times)


def align_to_lines(vocals: Path, lines: list[Line], profile: Profile) -> list[Line]:
    """Pose le mot-à-mot sur des lignes déjà synchronisées (LRC ligne-à-ligne).

    Chaque ligne est alignée dans [début − marge, début suivant + marge]. Une
    ligne impossible à aligner (fenêtre trop courte, texte vide) garde des
    timecodes interpolés : on ne perd jamais la synchro de ligne d'origine.
    """
    if not lines:
        return []
    print(f"  [MMS_FA] mot-à-mot dans les lignes LRC device={profile.device} — "
          f"{len(lines)} lignes …", flush=True)
    emission, spf = _emission(vocals, profile.device)
    n_frames = emission.size(0)
    total = n_frames * spf

    out: list[Line] = []
    prev_end = 0.0  # les lignes s'enchaînent : une fenêtre ne remonte pas avant la fin de la précédente
    for i, line in enumerate(lines):
        tokens = [w for ln_word in line.words for w in ln_word.text.split()]
        next_start = lines[i + 1].start if i + 1 < len(lines) else min(total, line.start + _MAX_LINE_SPAN)
        next_start = min(next_start, line.start + _MAX_LINE_SPAN)
        normalized = [_normalize(t) for t in tokens]
        alignable = [n for n in normalized if n]

        f0 = max(0, int((line.start - _PAD_BEFORE) / spf), int(prev_end / spf))
        f1 = min(n_frames, int((next_start + _PAD_AFTER) / spf))
        # CTC : il faut au moins une frame par caractère (+ blancs entre lettres répétées).
        needed = sum(len(n) for n in alignable) + len(alignable)
        aligned = None
        if alignable and f1 - f0 >= needed:
            try:
                spans = _force_align(emission[f0:f1], alignable)
                aligned = _rebuild_lines([tokens], normalized,
                                         [((f0 + a) * spf, (f0 + b) * spf) for a, b in spans])
            except Exception:  # fenêtre incompatible avec le texte (CTC impossible)
                aligned = None
        if not aligned:
            aligned = [interpolate_words(tokens, max(line.start, prev_end), next_start)]
        out.extend(aligned)
        prev_end = aligned[-1].end
    return out


def interpolate_words(tokens: list[str], start: float, next_start: float) -> Line:
    """Répartit les mots d'une ligne sur sa durée, au prorata de leur longueur.

    Filet de sécurité quand l'alignement est impossible : la ligne garde son
    début exact et le surlignage progresse quand même mot par mot.
    """
    if not tokens:
        return Line(start=start, end=start, words=[])
    # Durée chantée plausible : ~0,3 s par mot, bornée par la ligne suivante.
    span = max(0.3, min(next_start - start, 0.3 * len(tokens) + 0.5) if next_start > start else 0.3 * len(tokens))
    weights = [max(1, len(t)) for t in tokens]
    total = sum(weights)
    words, t = [], start
    for tok, w in zip(tokens, weights):
        d = span * w / total
        words.append(Word(text=tok, start=round(t, 3), end=round(t + d, 3)))
        t += d
    return Line(start=start, end=words[-1].end, words=words)


def _rebuild_lines(
    line_words: list[list[str]],
    normalized: list[str],
    times: list[tuple[float, float]],
) -> list[Line]:
    """Recolle les timecodes (dans l'ordre des mots alignables) sur les lignes."""
    lines: list[Line] = []
    ti = 0          # curseur dans `times` (mots alignables seulement)
    ni = 0          # curseur global dans `normalized`
    last_end = times[0][0] if times else 0.0

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
