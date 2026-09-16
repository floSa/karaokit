#!/usr/bin/env bash
# Bootstrap du projet Karaokit — installe tout sans sudo.
#   - ffmpeg (build statique dans scripts/bin, si absent du système)
#   - uv (gestionnaire Python) + Python 3.12 + dépendances (CPU ou GPU)
#   - Node.js (via nvm) + dépendances de l'app web, puis build
#
# Usage :
#   scripts/bootstrap.sh gpu     # NVIDIA CUDA (wheels PyTorch cu128)
#   scripts/bootstrap.sh cpu     # sans GPU (défaut)
set -euo pipefail

VARIANT="${1:-cpu}"
case "$VARIANT" in cpu|gpu) ;; *) echo "Variante inconnue : $VARIANT (cpu|gpu)"; exit 1 ;; esac
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/scripts/bin"
mkdir -p "$BIN"

echo "==> Projet : $ROOT   (variante: $VARIANT)"

# --- 1. ffmpeg (build statique, sans sudo) --------------------------------
if command -v ffmpeg >/dev/null 2>&1; then
  echo "==> ffmpeg déjà présent : $(command -v ffmpeg)"
elif [ -x "$BIN/ffmpeg" ]; then
  echo "==> ffmpeg déjà installé dans $BIN"
else
  echo "==> Installation de ffmpeg (build statique John Van Sickle)…"
  TMP="$(mktemp -d)"
  case "$(uname -m)" in
    x86_64)  URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" ;;
    aarch64) URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz" ;;
    *) echo "Architecture $(uname -m) non gérée, installe ffmpeg manuellement." ; exit 1 ;;
  esac
  curl -L "$URL" -o "$TMP/ffmpeg.tar.xz"
  tar -xf "$TMP/ffmpeg.tar.xz" -C "$TMP"
  DIR="$(find "$TMP" -maxdepth 1 -type d -name 'ffmpeg-*-static' | head -1)"
  cp "$DIR/ffmpeg" "$DIR/ffprobe" "$BIN/"
  rm -rf "$TMP"
  echo "==> ffmpeg installé dans $BIN"
fi

# --- 2. Python via uv ------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installation de uv…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "==> Dépendances Python ($VARIANT)…"
( cd "$ROOT" && uv sync --python 3.12 --extra "$VARIANT" )

# --- 3. Node.js via nvm + app web ------------------------------------------
export NVM_DIR="$HOME/.nvm"
if [ ! -s "$NVM_DIR/nvm.sh" ]; then
  echo "==> Installation de nvm…"
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | PROFILE=/dev/null bash
fi
# nvm n'est pas compatible avec 'set -u' : on le relâche autour de nvm.
set +u
# shellcheck disable=SC1091
. "$NVM_DIR/nvm.sh"
nvm install --lts >/dev/null
nvm use --lts >/dev/null
set -u
echo "==> Dépendances web + build…"
( cd "$ROOT/web" && npm ci && npm run build )

echo ""
echo "Bootstrap terminé."
echo "   Traiter un morceau :  uv run karaoke build \"chemin/vers/morceau.flac\""
echo "   Lecteur + éditeur  :  uv run karaoke serve     (http://localhost:8765)"
