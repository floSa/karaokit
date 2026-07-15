"""Brique 1 — Séparation voix / instrumental avec Demucs.

On fait un split "2 stems" (voix / accompagnement) : c'est tout ce dont le
karaoké a besoin. On produit :
  - no_vocals.<ext> : la piste instrumentale (à chanter par-dessus)
  - vocals.<ext>    : la voix isolée (sert à la transcription/synchro)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .config import Profile


def separate(audio: Path, out_dir: Path, profile: Profile, as_mp3: bool = True) -> dict[str, Path]:
    """Sépare `audio` en voix + instrumental via Demucs (ligne de commande).

    Retourne {"vocals": Path, "no_vocals": Path}.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = "mp3" if as_mp3 else "wav"

    # Demucs écrit dans <tmp>/<model>/<nom_du_morceau>/{vocals,no_vocals}.<ext>
    tmp_root = out_dir / "_demucs"
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", profile.demucs_model,
        "-d", profile.device,
        "-o", str(tmp_root),
    ]
    if as_mp3:
        cmd += ["--mp3", "--mp3-bitrate", "256"]
    cmd.append(str(audio))

    print(f"  [demucs] modèle={profile.demucs_model} device={profile.device} …", flush=True)
    subprocess.run(cmd, check=True)

    produced = tmp_root / profile.demucs_model / audio.stem
    vocals_src = produced / f"vocals.{ext}"
    instru_src = produced / f"no_vocals.{ext}"
    if not vocals_src.exists() or not instru_src.exists():
        raise RuntimeError(f"Sortie Demucs introuvable dans {produced}")

    # On range les stems avec des noms stables
    vocals_dst = out_dir / f"vocals.{ext}"
    instru_dst = out_dir / f"instrumental.{ext}"
    vocals_src.replace(vocals_dst)
    instru_src.replace(instru_dst)

    # Nettoyage du dossier temporaire de Demucs
    _rmtree(tmp_root)

    return {"vocals": vocals_dst, "no_vocals": instru_dst}


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
