"""Orchestration du pipeline complet.

Enchaîne : séparation → paroles (en ligne) → synchro (si besoin) → écriture des
sorties dans la bibliothèque (dossier servi par l'app web).

Optimisations de débit :
- la recherche de paroles (réseau) tourne **en parallèle** de Demucs (GPU/CPU) ;
- pour un album, les recherches de paroles de TOUS les morceaux partent dès le
  début, et les modèles (Demucs, MMS_FA, Whisper) sont chargés une seule fois ;
- chaque étape est chronométrée (`timings` dans karaoke.json).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from . import align, lrc, lyrics, metadata, separate, transcribe, verify
from .config import Profile
from .jobs import AUDIO_EXTS  # extensions audio reconnues
from .utils import atomic_write_text, check_ffmpeg, probe_duration, slugify

# Dérive médiane (s) au-delà de laquelle un ré-alignement mot-à-mot est jugé
# non fiable et rejeté au profit de la synchro en ligne existante.
REALIGN_MAX_DRIFT = 1.5

# Recherches de paroles concurrentes (réseau) pour un album.
_LYRICS_WORKERS = 4


def _median_drift(a: list, b: list) -> float | None:
    """Dérive médiane (s) entre les débuts de ligne de deux séquences (par index)."""
    import statistics

    n = min(len(a), len(b))
    if n == 0:
        return None
    diffs = [abs(a[i].start - b[i].start) for i in range(n)]
    return statistics.median(diffs)


@contextmanager
def _timed(timings: dict, key: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        timings[key] = round(time.perf_counter() - t0, 2)


def _identify(audio_path: Path, title: str | None, artist: str | None):
    m_title, m_artist = metadata.read_metadata(audio_path)
    title = title or m_title
    artist = artist or m_artist
    slug = slugify(f"{artist}-{title}" if artist else title)
    return title, artist, slug


def build(
    audio_path: Path,
    library_dir: Path,
    profile: Profile,
    title: str | None = None,
    artist: str | None = None,
    language: str | None = None,
    force: bool = False,
    realign: bool = False,
    word_level: bool = True,
    lyrics_future: Future | None = None,
    update_index: bool = True,
    progress: Callable[..., None] | None = None,
    return_skipped: bool = False,
):
    """Génère un karaoké complet pour `audio_path`. Renvoie le dossier produit.

    realign    : ignore la synchro de ligne en ligne et ré-aligne tout le texte
                 sur la voix (garde-fou anti-dérive).
    word_level : pose le mot-à-mot dans les lignes d'un LRC ligne-à-ligne (défaut).
    lyrics_future : recherche de paroles déjà lancée (mode album).
    progress   : rappel `progress(étape, **infos)` (file de traitement de l'app web).
    return_skipped : renvoie (dossier, déjà_présent) au lieu du seul dossier.
    """
    notify = progress or (lambda *a, **k: None)
    check_ffmpeg()
    audio_path = audio_path.expanduser().resolve()
    if not audio_path.exists():
        raise FileNotFoundError(audio_path)

    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    title, artist, slug = _identify(audio_path, title, artist)
    song_dir = library_dir / slug
    if (song_dir / "karaoke.json").exists() and not (force or realign):
        print(f"Déjà présent : {song_dir} (--force pour recalculer, --realign pour re-synchroniser)")
        return (song_dir, True) if return_skipped else song_dir
    song_dir.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(audio_path)

    notify("separation", slug=slug, title=title, artist=artist)
    print(f"Morceau : {artist + ' — ' if artist else ''}{title}")
    print(f"   Device : {profile.device}  |  Sortie : {song_dir}")

    with ThreadPoolExecutor(max_workers=1) as pool:
        # 2) Paroles en ligne — lancées TOUT DE SUITE, en parallèle de Demucs.
        if lyrics_future is None:
            lyrics_future = pool.submit(lyrics.fetch_lyrics, title, artist, duration)

        # 1) Séparation voix / instrumental (avec cache : on ne relance pas
        #    Demucs si les stems existent déjà).
        print("1/4  Séparation voix/instrumental")
        instru, voc = song_dir / "instrumental.mp3", song_dir / "vocals.mp3"
        with _timed(timings, "separation"):
            if instru.exists() and voc.exists() and not force:
                print("   Stems déjà présents — réutilisation (pas de Demucs)")
                stems = {"no_vocals": instru, "vocals": voc}
            else:
                stems = separate.separate(audio_path, song_dir, profile)

        print("2/4  Récupération des paroles en ligne")
        notify("lyrics")
        with _timed(timings, "lyrics_wait"):
            lyr = lyrics_future.result()

    # Contrôle : une recherche floue peut ramener les paroles d'un autre morceau.
    if lyr and not lyr.trusted:
        notify("check")
        with _timed(timings, "lyrics_check"):
            ok, score, detected = verify.lyrics_match(stems["vocals"], lyr.text, profile, language)
        shown = f"{score:.2f}" if score is not None else "n/a"
        if ok:
            print(f"   Paroles vérifiées sur la voix (recouvrement {shown})")
        else:
            print(f"   Paroles rejetées : elles ne correspondent pas à la voix "
                  f"(recouvrement {shown} < {verify.MIN_OVERLAP}) — {lyr.source}")
            lyr = None
        language = language or detected

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
    notify("sync")

    if online_lines is not None and not realign:
        # Niveau 1 : LRC synchronisé en ligne.
        print(f"   LRC synchronisé trouvé ({lyr.source})")
        already_words = any(len(ln.words) > 1 for ln in online_lines)
        if word_level and not already_words and online_lines:
            print("3/4  Synchronisation : lignes fournies — mot-à-mot posé dans chaque ligne")
            with _timed(timings, "sync"):
                lines = align.align_to_lines(stems["vocals"], online_lines, profile)
            lyrics_source = f"{lyr.source} + mot-à-mot"
        else:
            print("3/4  Synchronisation : déjà fournie en ligne")
            lines = online_lines
            lyrics_source = lyr.source
    elif plain_text:
        # Niveau 2 : on a le TEXTE propre -> on l'aligne mot-à-mot sur la voix.
        origin = "ré-aligné mot-à-mot" if online_lines is not None else "alignement forcé"
        print(f"   Texte disponible ({lyr.source}) — {origin} sur la voix isolée")
        print("3/4  Synchronisation (alignement forcé du texte)")
        with _timed(timings, "sync"):
            aligned = align.align_lyrics(stems["vocals"], plain_text, profile, language=language)

        if online_lines is not None:
            # Garde-fou : on ne remplace une bonne synchro en ligne par le
            # mot-à-mot que si l'alignement ne dérive pas trop (auto-contrôle).
            drift = _median_drift(aligned, online_lines)
            if drift is not None and drift > REALIGN_MAX_DRIFT:
                print(f"   Ré-alignement rejeté (dérive médiane {drift:.1f}s > "
                      f"{REALIGN_MAX_DRIFT}s) — on garde la synchro en ligne.")
                lines = online_lines
                lyrics_source = f"{lyr.source} (ré-alignement rejeté, dérive {drift:.1f}s)"
            else:
                d = f" (dérive {drift:.2f}s)" if drift is not None else ""
                print(f"   Ré-alignement accepté{d}")
                lines = aligned
                lyrics_source = f"{lyr.source} + {origin}"
        else:
            lines = aligned
            lyrics_source = f"{lyr.source} + {origin}"
    else:
        # Niveau 3 : aucune parole fiable -> transcription à l'aveugle de la voix.
        print("   Aucune parole en ligne fiable — transcription automatique de la voix")
        print("3/4  Transcription + synchronisation (WhisperX)")
        with _timed(timings, "sync"):
            lines = transcribe.transcribe_and_align(stems["vocals"], profile, language=language)
        # Les segments WhisperX sont souvent de longues phrases : on les recoupe
        # en fragments chantables pour l'affichage karaoké.
        lines = transcribe.split_long_lines(lines)
        lyrics_source = "transcription automatique (WhisperX)"

    lines = transcribe.remove_overlaps(lines)
    if not lines:
        print("   Aucune parole synchronisée produite (karaoké instrumental).")

    # 4) Écriture des sorties
    print("4/4  Écriture des fichiers")
    notify("writing")
    atomic_write_text(song_dir / "lyrics.lrc", lrc.write_lrc(lines, title, artist))

    timings["total"] = round(time.perf_counter() - t_start, 2)
    manifest = {
        "slug": slug,
        "title": title,
        "artist": artist,
        "duration": round(duration, 2) if duration else None,
        "instrumental": stems["no_vocals"].name,
        "vocals": stems["vocals"].name,
        "lyrics_source": lyrics_source,
        "wordLevel": any(len(ln.words) > 1 for ln in lines),   # surlignage mot-à-mot possible ?
        "device": profile.device,
        "timings": timings,
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
    # Atomique : le serveur peut lire ce fichier pendant que le traitement tourne.
    atomic_write_text(song_dir / "karaoke.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    if update_index:
        _update_index(library_dir)
    steps = "  ".join(f"{k}={v}s" for k, v in timings.items())
    print(f"Terminé : {song_dir}  ({steps})")
    return (song_dir, False) if return_skipped else song_dir


def build_folder(
    folder: Path,
    library_dir: Path,
    profile: Profile,
    language: str | None = None,
    force: bool = False,
    realign: bool = False,
    word_level: bool = True,
) -> list[Path]:
    """Traite tous les fichiers audio d'un dossier (album). Renvoie les dossiers produits."""
    folder = folder.expanduser().resolve()
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXTS)
    if not files:
        print(f"Aucun fichier audio trouvé dans {folder}")
        return []

    print(f"{len(files)} fichier(s) à traiter dans {folder}\n")
    t0 = time.perf_counter()
    done: list[Path] = []
    with ThreadPoolExecutor(max_workers=_LYRICS_WORKERS) as pool:
        # Toutes les recherches de paroles partent maintenant ; le GPU enchaîne
        # les séparations pendant que le réseau travaille.
        futures: dict[Path, Future] = {}
        for f in files:
            try:
                title, artist, slug = _identify(f.resolve(), None, None)
            except Exception:
                continue
            if (library_dir / slug / "karaoke.json").exists() and not (force or realign):
                continue
            futures[f] = pool.submit(lyrics.fetch_lyrics, title, artist, probe_duration(f))

        for i, f in enumerate(files, 1):
            print(f"── [{i}/{len(files)}] {f.name} " + "─" * 30)
            try:
                done.append(build(f, library_dir, profile, language=language, force=force,
                                  realign=realign, word_level=word_level,
                                  lyrics_future=futures.get(f), update_index=False))
            except Exception as exc:  # un fichier qui échoue ne bloque pas les autres
                print(f"   Échec sur {f.name} : {exc}")
            print()
    _update_index(library_dir)
    print(f"Album terminé : {len(done)}/{len(files)} morceau(x) traité(s) "
          f"en {time.perf_counter() - t0:.0f} s.")
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
    atomic_write_text(library_dir / "index.json", json.dumps(entries, ensure_ascii=False, indent=2))
