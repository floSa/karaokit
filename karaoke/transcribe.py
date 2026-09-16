"""Brique 3 — Transcription + synchronisation (forced alignment) avec WhisperX.

On transcrit la piste voix isolée puis on aligne chaque mot sur l'audio
(wav2vec2) pour obtenir des timestamps mot-à-mot (< 100 ms). On génère :
  - une structure "lignes de mots" utilisée par l'app web (surlignage précis)

Astuce qualité : on transcrit toujours la VOIX SÉPARÉE (pas le mix), l'ASR est
bien plus fiable sans la musique par-dessus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Profile
from .utils import preload_cuda_libs

_MODELS: dict[tuple, object] = {}  # modèles WhisperX chargés une fois par processus


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Line:
    start: float
    end: float
    words: list[Word] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()


def transcribe_and_align(
    vocals: Path,
    profile: Profile,
    language: str | None = None,
) -> list[Line]:
    """Transcrit + aligne la piste voix. Renvoie une liste de lignes horodatées."""
    preload_cuda_libs()  # sinon « libcublas.so.12 is not found » sur GPU
    try:
        import whisperx
    except ImportError as exc:
        raise RuntimeError(
            "La lib 'whisperx' n'est pas installée (voir requirements)."
        ) from exc

    device = profile.device
    print(f"  [whisperx] modèle={profile.whisper_model} device={device} …", flush=True)

    audio = whisperx.load_audio(str(vocals))

    key = ("asr", profile.whisper_model, device, language)
    if key not in _MODELS:
        _MODELS[key] = whisperx.load_model(
            profile.whisper_model,
            device,
            compute_type=profile.whisper_compute,
            language=language,
        )
    model = _MODELS[key]
    batch_size = 16 if profile.is_gpu else 4
    result = model.transcribe(audio, batch_size=batch_size, language=language)
    lang = result.get("language", language or "en")

    # Alignement forcé mot-à-mot
    akey = ("align", lang, device)
    if akey not in _MODELS:
        _MODELS[akey] = whisperx.load_align_model(language_code=lang, device=device)
    align_model, meta = _MODELS[akey]
    aligned = whisperx.align(
        result["segments"], align_model, meta, audio, device,
        return_char_alignments=False,
    )

    return _to_lines(aligned.get("segments", []))


def remove_overlaps(lines: list[Line]) -> list[Line]:
    """Garantit des mots strictement enchaînés (début croissant, fin ≤ début suivant).

    Les alignements par fenêtre ou les LRC communautaires peuvent faire déborder
    un mot sur le suivant : deux mots « en cours » à l'écran. On rogne la fin du
    premier (sans jamais le rendre négatif) et on recalcule les bornes de ligne.
    """
    words = [w for ln in lines for w in ln.words]
    for a, b in zip(words, words[1:]):
        if b.start < a.start:
            b.start = a.start
        if a.end > b.start:
            a.end = max(a.start, b.start)
        if b.end < b.start:
            b.end = b.start
    for ln in lines:
        if ln.words:
            ln.start, ln.end = ln.words[0].start, ln.words[-1].end
    return lines


def split_long_lines(lines: list[Line], max_words: int = 9) -> list[Line]:
    """Découpe les lignes trop longues (ex. segments WhisperX) en fragments
    chantables, en coupant de préférence après une ponctuation.
    """
    out: list[Line] = []
    for ln in lines:
        if len(ln.words) <= max_words:
            out.append(ln)
            continue
        chunk: list[Word] = []
        for w in ln.words:
            chunk.append(w)
            ends_punct = w.text[-1:] in ".,;:?!…»"
            if len(chunk) >= max_words or (ends_punct and len(chunk) >= max_words // 2):
                out.append(Line(chunk[0].start, chunk[-1].end, chunk))
                chunk = []
        if chunk:
            out.append(Line(chunk[0].start, chunk[-1].end, chunk))
    return out


def _to_lines(segments: list[dict]) -> list[Line]:
    """Convertit les segments WhisperX en lignes/mots propres."""
    lines: list[Line] = []
    for seg in segments:
        words: list[Word] = []
        for w in seg.get("words", []):
            # Certains mots (ponctuation) n'ont pas de timestamp : on les rattache
            start = w.get("start")
            end = w.get("end")
            token = (w.get("word") or "").strip()
            if not token:
                continue
            if start is None or end is None:
                if words:  # rattache au mot précédent
                    words[-1].text += token
                continue
            words.append(Word(text=token, start=float(start), end=float(end)))

        if not words:
            continue
        lines.append(Line(start=words[0].start, end=words[-1].end, words=words))
    return lines
