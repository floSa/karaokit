"""Orchestration du pipeline complet.

Enchaîne : séparation → paroles (en ligne) → synchro (si besoin) → écriture des
sorties dans la bibliothèque (dossier servi par l'app web).
"""

from __future__ import annotations

import json
from pathlib import Path

from . import align, lrc, lyrics, metadata, separate, transcribe
from .config import Profile
from .utils import check_ffmpeg, slugify

# Extensions audio reconnues pour le traitement d'un dossier entier.
AUDIO_EXTS = {".flac", ".mp3", ".wav", ".m4a", ".ogg", ".opus", ".aac", ".wma"}

# Dérive médiane (s) au-delà de laquelle un ré-alignement mot-à-mot est jugé
# non fiable et rejeté au profit de la synchro en ligne existante.
REALIGN_MAX_DRIFT = 1.5


def _median_drift(a: list, b: list) -> float | None:
    """Dérive médiane (s) entre les débuts de ligne de deux séquences (par index)."""
    import statistics

    n = min(len(a), len(b))
    if n == 0:
        return None
    diffs = [abs(a[i].start - b[i].start) for i in range(n)]
    return statistics.median(diffs)


def build(
    audio_path: Path,
    library_dir: Path,
    profile: Profile,
    title: str | None = None,
    artist: str | None = None,
    language: str | None = None,
    force: bool = False,
    realign: bool = False,
) -> Path:
    """Génère un karaoké complet pour `audio_path`. Renvoie le dossier produit.

    realign : force le niveau 2 (alignement mot-à-mot sur la voix) même quand un
    LRC synchronisé existe en ligne — utile si la synchro en ligne est mauvaise
    ou pour obtenir un surlignage mot-à-mot.
    """
    check_ffmpeg()
    audio_path = audio_path.expanduser().resolve()
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    m_title, m_artist = metadata.read_metadata(audio_path)
    title = title or m_title
    artist = artist or m_artist

    slug = slugify(f"{artist}-{title}" if artist else title)
    song_dir = library_dir / slug
    if (song_dir / "karaoke.json").exists() and not (force or realign):
        print(f"⏭  Déjà présent : {song_dir} (--force pour recalculer, --realign pour re-synchroniser)")
        return song_dir
    song_dir.mkdir(parents=True, exist_ok=True)

    print(f"🎧 Morceau : {artist + ' — ' if artist else ''}{title}")
    print(f"   Device : {profile.device}  |  Sortie : {song_dir}")

    # 1) Séparation voix / instrumental (avec cache : on ne relance pas Demucs
    #    si les stems existent déjà).
    print("1/4  Séparation voix/instrumental")
    instru, voc = song_dir / "instrumental.mp3", song_dir / "vocals.mp3"
    if instru.exists() and voc.exists() and not force:
        print("   ↺ Stems déjà présents — réutilisation (pas de Demucs)")
        stems = {"no_vocals": instru, "vocals": voc}
    else:
        stems = separate.separate(audio_path, song_dir, profile, as_mp3=True)

    # 2) Paroles en ligne (potentiellement déjà synchronisées)
    print("2/4  Récupération des paroles en ligne")
    lyr = lyrics.fetch_lyrics(title, artist)

    online_lines: list[transcribe.Line] | None = None
    plain_text: str | None = None
    if lyr:
        if lyr.synced:
            online_lines = lrc.parse_lrc(lyr.text)
            plain_text = "\n".join(ln.text for ln in online_lines)
        else:
            plain_text = lyr.text

    lines: list[transcribe.Line]
    lyrics_source: str

    if online_lines is not None and not realign:
        # Niveau 1 : LRC synchronisé récupéré tel quel.
        print(f"   ✓ LRC synchronisé trouvé ({lyr.source})")
        print("3/4  Synchronisation : déjà fournie en ligne")
        lines = online_lines
        lyrics_source = lyr.source
    elif plain_text:
        # Niveau 2 : on a le TEXTE propre -> on l'aligne mot-à-mot sur la voix.
        origin = "ré-aligné mot-à-mot" if online_lines is not None else "alignement forcé"
        print(f"   ✓ Texte disponible ({lyr.source}) — {origin} sur la voix isolée")
        print("3/4  Synchronisation (alignement forcé du texte)")
        aligned = align.align_lyrics(stems["vocals"], plain_text, profile, language=language)

        if online_lines is not None:
            # Garde-fou : on ne remplace une bonne synchro en ligne par le
            # mot-à-mot que si l'alignement ne dérive pas trop (auto-contrôle).
            drift = _median_drift(aligned, online_lines)
            if drift is not None and drift > REALIGN_MAX_DRIFT:
                print(f"   ⚠ Ré-alignement rejeté (dérive médiane {drift:.1f}s > "
                      f"{REALIGN_MAX_DRIFT}s) — on garde la synchro en ligne.")
                lines = online_lines
                lyrics_source = f"{lyr.source} (ré-alignement rejeté, dérive {drift:.1f}s)"
            else:
                d = f" (dérive {drift:.2f}s)" if drift is not None else ""
                print(f"   ✓ Ré-alignement accepté{d}")
                lines = aligned
                lyrics_source = f"{lyr.source} + {origin}"
        else:
            lines = aligned
            lyrics_source = f"{lyr.source} + {origin}"
    else:
        # Niveau 3 : aucune parole en ligne -> transcription à l'aveugle de la voix.
        print("   ⚠ Aucune parole en ligne — transcription automatique de la voix")
        print("3/4  Transcription + synchronisation (WhisperX)")
        lines = transcribe.transcribe_and_align(stems["vocals"], profile, language=language)
        # Les segments WhisperX sont souvent de longues phrases : on les recoupe
        # en fragments chantables pour l'affichage karaoké.
        lines = transcribe.split_long_lines(lines)
        lyrics_source = "transcription automatique (WhisperX)"

    if not lines:
        print("   ⚠ Aucune parole synchronisée produite (karaoké instrumental).")

    # 4) Écriture des sorties
    print("4/4  Écriture des fichiers")
    (song_dir / "lyrics.lrc").write_text(lrc.write_lrc(lines, title, artist), encoding="utf-8")

    word_level = any(len(ln.words) > 1 for ln in lines)
    manifest = {
        "slug": slug,
        "title": title,
        "artist": artist,
        "instrumental": stems["no_vocals"].name,
        "vocals": stems["vocals"].name,
        "lyrics_source": lyrics_source,
        "wordLevel": word_level,   # surlignage mot-à-mot possible ?
        "device": profile.device,
        "lines": [
            {
                "start": round(ln.start, 3),
                "end": round(ln.end, 3),
                "words": [
                    {"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
                    for w in ln.words
                ],
            }
            for ln in lines
        ],
    }
    (song_dir / "karaoke.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _update_index(library_dir)
    print(f"✅ Terminé : {song_dir}")
    return song_dir


def build_folder(
    folder: Path,
    library_dir: Path,
    profile: Profile,
    language: str | None = None,
    force: bool = False,
    realign: bool = False,
) -> list[Path]:
    """Traite tous les fichiers audio d'un dossier (album). Renvoie les dossiers produits."""
    folder = folder.expanduser().resolve()
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXTS)
    if not files:
        print(f"Aucun fichier audio trouvé dans {folder}")
        return []

    print(f"📀 {len(files)} fichier(s) à traiter dans {folder}\n")
    done: list[Path] = []
    for i, f in enumerate(files, 1):
        print(f"── [{i}/{len(files)}] {f.name} " + "─" * 30)
        try:
            done.append(build(f, library_dir, profile, language=language,
                              force=force, realign=realign))
        except Exception as exc:  # un fichier qui échoue ne bloque pas les autres
            print(f"   ❌ Échec sur {f.name} : {exc}")
        print()
    print(f"✅ Album terminé : {len(done)}/{len(files)} morceau(x) traité(s).")
    return done


def _update_index(library_dir: Path) -> None:
    """(Re)génère library/index.json listant tous les morceaux disponibles."""
    entries = []
    for karaoke_json in sorted(library_dir.glob("*/karaoke.json")):
        try:
            data = json.loads(karaoke_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        entries.append(
            {
                "slug": data["slug"],
                "title": data.get("title", ""),
                "artist": data.get("artist", ""),
                "hasLyrics": bool(data.get("lines")),
                "wordLevel": bool(data.get("wordLevel")),
            }
        )
    (library_dir / "index.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
