"""Interface en ligne de commande.

Exemples :
  python -m karaoke build "morceau.flac"
  python -m karaoke build "Artiste - Titre.flac" --device cpu --language fr
  python -m karaoke list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .config import build_profile, detect_device
from .pipeline import build, build_folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="karaoke", description="Génère un karaoké maison depuis un fichier audio."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Traiter un fichier audio ou un dossier (album)")
    p_build.add_argument("audio", type=Path, help="Fichier audio (FLAC, MP3…) ou dossier d'album")
    p_build.add_argument(
        "--device", choices=["auto", "cpu", "cuda"], default="auto",
        help="Matériel à utiliser (défaut : auto-détection).",
    )
    p_build.add_argument("--title", help="Titre (sinon tags/nom de fichier). Ignoré pour un dossier.")
    p_build.add_argument("--artist", help="Artiste (sinon tags/arborescence). Ignoré pour un dossier.")
    p_build.add_argument("--language", help="Code langue ISO (ex: fr, en). Auto si absent.")
    p_build.add_argument(
        "--out", type=Path, default=config.DEFAULT_LIBRARY_DIR,
        help="Dossier bibliothèque de sortie.",
    )
    p_build.add_argument("--force", action="store_true", help="Tout recalculer (y compris Demucs).")
    p_build.add_argument(
        "--realign", action="store_true",
        help="Ignorer la synchro de ligne en ligne et ré-aligner tout le texte sur la voix.",
    )
    p_build.add_argument(
        "--line-only", action="store_true",
        help="Ne pas poser le mot-à-mot dans un LRC ligne-à-ligne (le garder tel quel).",
    )

    sub.add_parser("list", help="Lister les morceaux de la bibliothèque")

    p_export = sub.add_parser("export", help="Générer une vidéo karaoké MP4 (morceau déjà traité)")
    p_export.add_argument("song", help="slug du morceau, chemin de son dossier, ou 'all' pour tout")
    p_export.add_argument("--width", type=int, default=1280, help="Largeur vidéo (défaut 1280).")
    p_export.add_argument("--height", type=int, default=720, help="Hauteur vidéo (défaut 720).")

    p_serve = sub.add_parser("serve", help="Servir l'app web + éditeur de synchro (sauvegarde locale)")
    p_serve.add_argument("--port", type=int, default=8765, help="Port (défaut 8765).")
    p_serve.add_argument("--library", type=Path, default=config.DEFAULT_LIBRARY_DIR,
                         help="Dossier bibliothèque à servir.")
    p_serve.add_argument("--music", type=Path, action="append",
                         help="Dossier de musique parcourable depuis l'app (répétable ; "
                              "défaut : ~/Music et C:\\Users\\<vous>\\Music).")
    p_serve.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto",
                         help="Matériel pour les traitements lancés depuis l'app.")

    args = parser.parse_args(argv)

    if args.command == "list":
        return _cmd_list()

    if args.command == "export":
        return _cmd_export(args)

    if args.command == "serve":
        from .server import serve
        serve(port=args.port, lib_root=args.library, music_roots=args.music, device=args.device)
        return 0

    if args.command == "build":
        device = detect_device(args.device)
        profile = build_profile(device)
        try:
            if args.audio.expanduser().is_dir():
                build_folder(
                    folder=args.audio,
                    library_dir=args.out,
                    profile=profile,
                    language=args.language,
                    force=args.force,
                    realign=args.realign,
                    word_level=not args.line_only,
                )
            else:
                build(
                    audio_path=args.audio,
                    library_dir=args.out,
                    profile=profile,
                    title=args.title,
                    artist=args.artist,
                    language=args.language,
                    force=args.force,
                    realign=args.realign,
                    word_level=not args.line_only,
                )
        except Exception as exc:  # message clair plutôt qu'un traceback brut
            print(f"❌ Erreur : {exc}", file=sys.stderr)
            return 1
        return 0

    return 0


def _cmd_export(args) -> int:
    from .export_video import export_video

    res = (args.width, args.height)

    # 'all' -> exporte tous les morceaux de la bibliothèque.
    if args.song == "all":
        dirs = sorted(p.parent for p in config.DEFAULT_LIBRARY_DIR.glob("*/karaoke.json"))
        if not dirs:
            print("Bibliothèque vide.")
            return 0
        ok = 0
        for d in dirs:
            print(f"── {d.name}")
            try:
                export_video(d, res)
                ok += 1
            except Exception as exc:
                print(f"   ❌ {exc}")
        print(f"\n✅ {ok}/{len(dirs)} vidéo(s) exportée(s).")
        return 0

    song = Path(args.song)
    song_dir = song if song.is_dir() else config.DEFAULT_LIBRARY_DIR / args.song
    if not (song_dir / "karaoke.json").exists():
        print(f"❌ Morceau introuvable : {song_dir} (lance d'abord 'build')", file=sys.stderr)
        return 1
    try:
        export_video(song_dir, res)
    except Exception as exc:
        print(f"❌ Erreur export : {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_list() -> int:
    import json

    index = config.DEFAULT_LIBRARY_DIR / "index.json"
    if not index.exists():
        print("Bibliothèque vide. Lance d'abord : python -m karaoke build <fichier>")
        return 0
    entries = json.loads(index.read_text(encoding="utf-8"))
    if not entries:
        print("Bibliothèque vide.")
        return 0
    for e in entries:
        mark = "🎤" if e["hasLyrics"] else "🎹"
        artist = f"{e['artist']} — " if e["artist"] else ""
        print(f"  {mark} {artist}{e['title']}  ({e['slug']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
