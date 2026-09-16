"""Brique 1 — Séparation voix / instrumental avec Demucs.

Le karaoké n'a besoin que de deux pistes : la voix (synchro + « guide ») et
l'instrumental (à chanter par-dessus). On en tire trois optimisations :

- **API Python en processus** (plus de sous-processus `python -m demucs`) : le
  modèle est chargé une seule fois et réutilisé pour tout un album.
- **Sous-modèle « voix » seul** : `htdemucs_ft` est un sac de 4 modèles
  spécialisés (batterie, basse, autre, voix) dont les poids forment une matrice
  identité — seul le 4ᵉ contribue à la voix. On ne fait tourner que lui
  (≈ 4× plus rapide, voix identique à 0,04 % près).
- **Instrumental = mix − voix** : complémentaire exact de la voix (rien ne se
  perd, contrairement à la somme des autres stems), et un seul passage réseau.

Les deux MP3 sont encodés en parallèle par ffmpeg.
"""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import Profile
from .utils import ffmpeg_bin

_SR = 44100  # fréquence native des modèles Demucs
_MODELS: dict[tuple[str, str], object] = {}  # cache (nom, device) -> modèle « voix »

# Débits MP3 : l'instrumental est ce qu'on écoute ; la voix ne sert que de guide
# et de source pour la synchro (analysée en mono 16 kHz) -> mono, encodage 2× plus court.
INSTRU_BITRATE = "256k"
VOCALS_BITRATE = "96k"


def _vocals_model(name: str, device: str):
    """Charge (une fois) le modèle Demucs et en extrait le sous-modèle « voix »."""
    key = (name, device)
    if key not in _MODELS:
        from demucs.apply import BagOfModels
        from demucs.pretrained import get_model

        model = get_model(name)
        if isinstance(model, BagOfModels):
            vi = model.sources.index("vocals")
            # Sac « spécialisé » (poids identité) : un seul modèle produit la voix.
            specialised = [i for i, w in enumerate(model.weights) if w[vi] != 0]
            if len(specialised) == 1:
                model = model.models[specialised[0]]
        _MODELS[key] = model.to(device).eval()
    return _MODELS[key]


def load_audio(path: Path, sample_rate: int = _SR, channels: int = 2):
    """Décode n'importe quel format en float32 (channels, N) via ffmpeg."""
    import numpy as np
    import torch

    raw = subprocess.run(
        [ffmpeg_bin(), "-v", "error", "-i", str(path),
         "-f", "f32le", "-ac", str(channels), "-ar", str(sample_rate), "-"],
        check=True, stdout=subprocess.PIPE,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.float32).reshape(-1, channels).T
    return torch.from_numpy(samples.copy())


def extract_vocals(mix, profile: Profile):
    """Renvoie la voix estimée (2, N) sur CPU pour un mix stéréo 44,1 kHz."""
    import torch
    from demucs.apply import apply_model

    model = _vocals_model(profile.demucs_model, profile.device)
    ref = mix.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    x = ((mix - mean) / std)[None]
    use_fp16 = profile.is_gpu  # demi-précision : même résultat (écart ~1e-3), ~20 % plus rapide
    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.float16, enabled=use_fp16):
        out = apply_model(model, x, device=profile.device, shifts=0, split=True,
                          overlap=0.25, progress=False)[0]
    vocals = out[model.sources.index("vocals")].float().cpu() * std + mean
    if profile.is_gpu:
        torch.cuda.empty_cache()
    return vocals


def _encode_mp3(wave, dst: Path, bitrate: str, mono: bool = False) -> None:
    subprocess.run(
        [ffmpeg_bin(), "-v", "error", "-y", "-f", "f32le", "-ar", str(_SR), "-ac", "2", "-i", "-",
         *(["-ac", "1"] if mono else []),
         "-c:a", "libmp3lame", "-b:a", bitrate, "-f", "mp3", str(dst)],
        input=wave.T.contiguous().numpy().tobytes(), check=True,
    )


def separate(audio: Path, out_dir: Path, profile: Profile) -> dict[str, Path]:
    """Sépare `audio` en voix + instrumental. Retourne {"vocals": Path, "no_vocals": Path}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"  [demucs] modèle={profile.demucs_model} (voix seule) device={profile.device} …", flush=True)

    mix = load_audio(audio)
    vocals = extract_vocals(mix, profile)
    instrumental = mix - vocals

    vocals_dst = out_dir / "vocals.mp3"
    instru_dst = out_dir / "instrumental.mp3"
    # Écriture atomique : un MP3 à moitié écrit ne doit jamais passer pour un cache valide.
    tmp_v, tmp_i = vocals_dst.with_suffix(".part.mp3"), instru_dst.with_suffix(".part.mp3")
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(_encode_mp3, instrumental, tmp_i, INSTRU_BITRATE),
                pool.submit(_encode_mp3, vocals, tmp_v, VOCALS_BITRATE, True)]
        for job in jobs:
            job.result()
    tmp_v.replace(vocals_dst)
    tmp_i.replace(instru_dst)
    return {"vocals": vocals_dst, "no_vocals": instru_dst}
