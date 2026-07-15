"""Lecture/écriture LRC et conversion vers le format interne (lignes de mots).

Gère le LRC standard ('[mm:ss.xx] texte') et le LRC "enhanced" avec des tags
mot-à-mot inline ('<mm:ss.xx>').
"""

from __future__ import annotations

import re

from .transcribe import Line, Word
from .utils import format_lrc_time

_LINE_TAG = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]")
_WORD_TAG = re.compile(r"<(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?>")


def _parse_time(m: re.Match) -> float:
    minutes = int(m.group(1))
    seconds = int(m.group(2))
    frac = m.group(3) or "0"
    frac_val = int(frac) / (10 ** len(frac))
    return minutes * 60 + seconds + frac_val


def parse_lrc(content: str) -> list[Line]:
    """Convertit un contenu LRC en liste de Line (avec mots si enhanced)."""
    lines: list[Line] = []
    raw_lines = content.splitlines()

    for raw in raw_lines:
        tags = list(_LINE_TAG.finditer(raw))
        if not tags:
            continue
        # Le texte est ce qui suit le dernier tag de ligne
        text_part = raw[tags[-1].end():]
        line_start = _parse_time(tags[-1])

        words = _parse_enhanced_words(text_part, line_start)
        if not words:
            continue

        # Un tag de ligne peut être répété (mêmes paroles à plusieurs temps)
        for tag in tags:
            start = _parse_time(tag)
            shift = start - line_start
            shifted = [Word(w.text, w.start + shift, w.end + shift) for w in words]
            lines.append(Line(start=start, end=shifted[-1].end, words=shifted))

    lines.sort(key=lambda ln: ln.start)
    return lines


def _parse_enhanced_words(text_part: str, line_start: float) -> list[Word]:
    """Découpe la portion texte en mots, en tenant compte des tags <mm:ss.xx>."""
    word_tags = list(_WORD_TAG.finditer(text_part))

    if not word_tags:
        # Pas de timing mot-à-mot : un seul "mot" = la ligne entière
        text = text_part.strip()
        if not text:
            return []
        return [Word(text=text, start=line_start, end=line_start)]

    words: list[Word] = []
    # Texte avant le premier tag mot (rare) rattaché au début de ligne
    positions = [(line_start, 0, word_tags[0].start())]
    for i, wt in enumerate(word_tags):
        start = _parse_time(wt)
        seg_start = wt.end()
        seg_end = word_tags[i + 1].start() if i + 1 < len(word_tags) else len(text_part)
        token = text_part[seg_start:seg_end].strip()
        if token:
            words.append(Word(text=token, start=start, end=start))

    # Estime la fin de chaque mot = début du suivant
    for i in range(len(words) - 1):
        words[i].end = words[i + 1].start
    if words:
        words[-1].end = words[-1].start + 0.6  # petite durée par défaut
    return words


def write_lrc(lines: list[Line], title: str = "", artist: str = "") -> str:
    """Sérialise des lignes en LRC standard (ligne par ligne)."""
    out: list[str] = []
    if title:
        out.append(f"[ti:{title}]")
    if artist:
        out.append(f"[ar:{artist}]")
    out.append("[re:karaoke-maison]")
    out.append("")
    for ln in lines:
        out.append(f"[{format_lrc_time(ln.start)}]{ln.text}")
    return "\n".join(out) + "\n"
