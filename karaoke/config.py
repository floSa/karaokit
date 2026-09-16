"""Configuration et détection du matériel (CPU vs GPU).

Le même code tourne sur CPU et sur GPU : on détecte automatiquement CUDA, et on
choisit des modèles adaptés (plus légers en CPU, plus lourds/précis en GPU).
On peut forcer le device avec --device.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def detect_device(preferred: str = "auto") -> str:
    """Retourne 'cuda' ou 'cpu'.

    preferred: 'auto' | 'cpu' | 'cuda'. En 'auto', on prend le GPU s'il est là.
    """
    if preferred == "cpu":
        return "cpu"

    try:
        import torch  # import tardif : torch est lourd à charger

        has_cuda = torch.cuda.is_available()
    except Exception:
        has_cuda = False

    if preferred == "cuda":
        if not has_cuda:
            raise RuntimeError(
                "GPU demandé (--device cuda) mais CUDA n'est pas disponible. "
                "Installe la variante GPU (requirements-gpu.txt) ou utilise --device cpu."
            )
        return "cuda"

    # auto
    return "cuda" if has_cuda else "cpu"


@dataclass(frozen=True)
class Profile:
    """Profil de modèles selon le device."""

    device: str
    demucs_model: str          # modèle de séparation
    whisper_model: str         # taille du modèle ASR
    whisper_compute: str       # type de calcul (float16 GPU / int8 CPU)
    verify_model: str          # Whisper rapide pour vérifier les paroles trouvées

    @property
    def is_gpu(self) -> bool:
        return self.device == "cuda"


def build_profile(device: str) -> Profile:
    """Choisit des modèles adaptés au device.

    Demucs : `htdemucs_ft` partout — on n'exécute que son sous-modèle « voix »
    (voir separate.py), donc le coût est celui d'un modèle simple.
    """
    if device == "cuda":
        return Profile(
            device="cuda",
            demucs_model="htdemucs_ft",
            whisper_model="large-v3",     # meilleure transcription
            whisper_compute="float16",
            verify_model="small",
        )
    return Profile(
        device="cpu",
        demucs_model="htdemucs_ft",
        whisper_model="small",            # compromis vitesse/qualité en CPU
        whisper_compute="int8",
        verify_model="base",
    )


# --- Chemins ---------------------------------------------------------------

# Racine du projet
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# La bibliothèque est servie directement par l'app web (dossier public de Vite).
DEFAULT_LIBRARY_DIR = PROJECT_ROOT / "web" / "public" / "library"

# Dossier de cache pour les fichiers de travail (stems bruts, etc.)
CACHE_DIR = PROJECT_ROOT / ".cache"
