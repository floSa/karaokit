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
    try:
        import whisperx
    except ImportError as exc:
        raise RuntimeError(
            "La lib 'whisperx' n'est pas installée (voir requirements)."
        ) from exc

    device = profile.device
    print(f"  [whisperx] modèle={profile.whisper_model} device={device} …", flush=True)

    audio = whisperx.load_audio(str(vocals))

    model = whisperx.load_model(
        profile.whisper_model,
        device,
        compute_type=profile.whisper_compute,
        language=language,
    )
    batch_size = 16 if profile.is_gpu else 4
    result = model.transcribe(audio, batch_size=batch_size, language=language)
    lang = result.get("language", language or "en")

    # Alignement forcé mot-à-mot
    align_model, meta = whisperx.load_align_model(language_code=lang, device=device)
    aligned = whisperx.align(
        result["segments"], align_model, meta, audio, device,
        return_char_alignments=False,
    )

    return _to_lines(aligned.get("segments", []))


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
