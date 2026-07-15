#!/usr/bin/env bash
# Bootstrap du projet karaoké — installe TOUT sans sudo.
#   - ffmpeg (build statique dans scripts/bin)
#   - Node.js (via nvm, dans ~/.nvm)
#   - environnement Python (venv + dépendances CPU ou GPU)
#   - dépendances de l'app web (npm install)
#
# Usage :
#   scripts/bootstrap.sh cpu     # variante CPU (défaut)
#   scripts/bootstrap.sh gpu     # variante GPU (NVIDIA CUDA)
set -euo pipefail

VARIANT="${1:-cpu}"
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
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64)  URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz" ;;
    aarch64) URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz" ;;
    *) echo "Architecture $ARCH non gérée, installe ffmpeg manuellement." ; exit 1 ;;
  esac
  curl -L "$URL" -o "$TMP/ffmpeg.tar.xz"
  tar -xf "$TMP/ffmpeg.tar.xz" -C "$TMP"
  DIR="$(find "$TMP" -maxdepth 1 -type d -name 'ffmpeg-*-static' | head -1)"
  cp "$DIR/ffmpeg" "$DIR/ffprobe" "$BIN/"
  rm -rf "$TMP"
  echo "==> ffmpeg installé dans $BIN"
fi

# --- 2. Node.js via nvm (sans sudo) ---------------------------------------
export NVM_DIR="$HOME/.nvm"
if command -v node >/dev/null 2>&1; then
  echo "==> Node déjà présent : $(node --version)"
else
  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    echo "==> Installation de nvm…"
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
  fi
  echo "==> Chargement de Node via nvm…"
  # nvm n'est pas compatible avec 'set -u' : on le relâche autour de nvm.
  set +u
  # shellcheck disable=SC1091
  . "$NVM_DIR/nvm.sh"
  nvm install --lts
  nvm use --lts
  set -u
fi

# --- 3. Environnement Python ----------------------------------------------
if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "==> Création du venv Python…"
  # Certains systèmes n'ont pas ensurepip (paquet python3-venv absent) : on crée
  # le venv sans pip puis on l'amorce avec get-pip.py (aucun sudo requis).
  if python3 -m venv "$ROOT/.venv" 2>/dev/null && [ -x "$ROOT/.venv/bin/pip" ]; then
    :
  else
    rm -rf "$ROOT/.venv"
    python3 -m venv --without-pip "$ROOT/.venv"
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$ROOT/scripts/get-pip.py"
    "$ROOT/.venv/bin/python" "$ROOT/scripts/get-pip.py"
    rm -f "$ROOT/scripts/get-pip.py"
  fi
fi
# shellcheck disable=SC1091
. "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip
echo "==> Installation des dépendances Python ($VARIANT)…"
pip install -r "$ROOT/requirements-$VARIANT.txt"

# --- 4. Dépendances web ----------------------------------------------------
if command -v node >/dev/null 2>&1; then
  echo "==> Installation des dépendances web…"
  ( cd "$ROOT/web" && npm install )
fi

echo ""
echo "✅ Bootstrap terminé."
echo "   Ajoute ffmpeg au PATH pour cette session :"
echo "     export PATH=\"$BIN:\$PATH\""
echo "   Active le venv :  source .venv/bin/activate"
echo "   Traite un morceau :  python -m karaoke build \"chemin/vers/morceau.flac\""
echo "   Lance l'app web :    cd web && npm run dev"
