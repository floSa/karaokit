"""Export d'une vidéo karaoké MP4 (sous-titres ASS incrustés, effet mot-à-mot).

À partir d'un morceau déjà traité (karaoke.json + instrumental), on génère un
fichier .ass avec l'effet karaoké `\\k` (remplissage progressif des mots) puis
on l'incruste sur un fond uni via ffmpeg (libass). Résultat : un MP4 lisible
partout (TV, téléphone), utile pour partager.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .utils import ffmpeg_bin, probe_duration

# Couleurs ASS au format &HAABBGGRR (alpha, bleu, vert, rouge).
_UNSUNG = "&H00EEB6AE"   # lavande (mot pas encore chanté) = #AEB6EE
_SUNG = "&H008D4DFF"     # rose (mot chanté)               = #FF4D8D
_BG_HEX = "0x0D1020"     # fond sombre, cohérent avec l'app web


def _ass_time(seconds: float) -> str:
    """Secondes -> 'H:MM:SS.cs' (centisecondes) attendu par ASS."""
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(lines: list[dict], width: int, height: int) -> str:
    """Construit le contenu ASS avec effet karaoké mot-à-mot."""
    fontsize = max(28, height // 13)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{fontsize},{_SUNG},{_UNSUNG},&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,5,80,80,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for i, line in enumerate(lines):
        words = line.get("words", [])
        if not words:
            continue
        start = line["start"]
        # La ligne reste affichée jusqu'au début de la suivante (ou +3 s à la fin).
        disp_end = lines[i + 1]["start"] if i + 1 < len(lines) else line["end"] + 3.0
        disp_end = max(disp_end, line["end"])

        text = _karaoke_text(words, disp_end)
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(disp_end)},Default,,0,0,0,,{text}"
        )
    return header + "\n".join(events) + "\n"


def _karaoke_text(words: list[dict], disp_end: float) -> str:
    """Génère '{\\kNN}mot ' avec des durées continues (sweep sans trou)."""
    parts: list[str] = []
    n = len(words)
    for j, w in enumerate(words):
        # Durée de surlignage = jusqu'au mot suivant (ou fin d'affichage pour le dernier).
        nxt = words[j + 1]["start"] if j + 1 < n else disp_end
        dur_cs = max(1, int(round((nxt - w["start"]) * 100)))
        token = str(w["text"]).replace("{", "(").replace("}", ")")
        parts.append(f"{{\\k{dur_cs}}}{token} ")
    return "".join(parts).rstrip()


def export_video(song_dir: Path, resolution: tuple[int, int] = (1280, 720)) -> Path:
    """Génère song_dir/karaoke.mp4. Renvoie le chemin de la vidéo."""
    song_dir = song_dir.expanduser().resolve()
    manifest = song_dir / "karaoke.json"
    if not manifest.exists():
        raise FileNotFoundError(f"karaoke.json introuvable dans {song_dir}")

    data = json.loads(manifest.read_text(encoding="utf-8"))
    lines = data.get("lines", [])
    instrumental = song_dir / data["instrumental"]
    if not instrumental.exists():
        raise FileNotFoundError(instrumental)

    width, height = resolution
    ass_content = build_ass(lines, width, height)
    (song_dir / "karaoke.ass").write_text(ass_content, encoding="utf-8")

    duration = probe_duration(instrumental)
    if duration is None:
        raise RuntimeError(f"Durée illisible : {instrumental}")
    out = song_dir / "karaoke.mp4"

    # On travaille depuis song_dir pour éviter tout échappement de chemin dans le filtre.
    cmd = [
        ffmpeg_bin(), "-y",
        "-f", "lavfi", "-i", f"color=c={_BG_HEX}:s={width}x{height}:d={duration:.3f}",
        "-i", data["instrumental"],
        "-vf", "ass=karaoke.ass",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "256k",
        "-shortest",
        "karaoke.mp4",
    ]
    print(f"  [ffmpeg] rendu vidéo {width}x{height} ({duration:.0f}s) …", flush=True)
    subprocess.run(cmd, check=True, cwd=song_dir,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    # On référence la vidéo dans le manifeste pour que l'app web propose le téléchargement.
    data["video"] = out.name
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Vidéo : {out}")
    return out
