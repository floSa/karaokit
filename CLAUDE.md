# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

**Karaokit** — karaoké maison. Un pipeline Python transforme un fichier audio
(FLAC/MP3/WAV) en karaoké (séparation voix/instru, paroles synchronisées), et une
app web React le lit. Le module Python s'importe sous le nom **`karaoke`** (le
projet s'appelle Karaokit, mais la commande reste `python -m karaoke …`).

## Contraintes d'environnement (à connaître AVANT tout)

La machine cible (WSL2) n'a **ni `sudo`, ni compilateur C/C++**. Conséquences
structurantes, déjà gérées — ne pas « réparer » en réintroduisant ces dépendances :

- **ffmpeg** est un build statique dans `scripts/bin/` (pas d'install système). Il
  doit être sur le PATH pour presque toute commande : `export PATH="$PWD/scripts/bin:$PATH"`.
  `utils.ffmpeg_bin()` le localise (PATH puis `scripts/bin/`).
- **L'alignement forcé (niveau 2) utilise `torchaudio.pipelines.MMS_FA`** (wheel
  précompilé), PAS `ctc-forced-aligner` (qui exige un compilateur C++ → échoue ici).
- Le venv est amorcé via `get-pip.py` quand `ensurepip` manque (`scripts/bootstrap.sh` gère ça).
- Node est installé via **nvm** (`~/.nvm`) ; charger avec `. "$HOME/.nvm/nvm.sh"`.
- `torchaudio.forced_align` est **déprécié en torchaudio 2.9** → garder `torchaudio<2.9`.

## Commandes

```bash
# Setup complet (sans sudo) — variante 'cpu' ou 'gpu'
scripts/bootstrap.sh cpu

# Toujours, avant d'utiliser le pipeline :
source .venv/bin/activate
export PATH="$PWD/scripts/bin:$PATH"

# Traiter un morceau / un album ; tags FLAC lus automatiquement (pas besoin de --title/--artist)
python -m karaoke build "morceau.flac" --language fr
python -m karaoke build "/chemin/vers/Album/" --language fr      # dossier = album
python -m karaoke build morceau.flac --realign                   # force le mot-à-mot (niveau 2)
python -m karaoke build morceau.flac --force                     # recalcule TOUT, y compris Demucs

python -m karaoke list
python -m karaoke export <slug>          # vidéo MP4 ; 'all' pour tous
python -m karaoke serve                  # http://localhost:8765 : lecteur + éditeur

# Tests (logique pure, aucune dépendance lourde requise)
python tests/test_core.py                # ou : python -m pytest tests/
python tests/test_core.py                # (pas de sélection par test ; fichier unique)

# App web
cd web && npm install
npm run dev        # http://localhost:5173 (rechargement à chaud ; l'éditeur POST vers :8765)
npm run build      # requis avant `python -m karaoke serve`
```

## Architecture (big picture)

Doc détaillée : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Points qui
nécessitent de lire plusieurs fichiers :

**Dégradation en 3 niveaux pour la synchro** (cœur du projet, dans `pipeline.build`) :
1. **LRC synchronisé** trouvé en ligne (`lyrics.py` + `lrc.py`) → utilisé tel quel.
2. Sinon **texte seul** trouvé → **alignement forcé** du texte sur la voix isolée
   (`align.py`, MMS_FA). C'est ce qui différencie Karaokit d'OpenKara : on fabrique
   la synchro quand elle n'existe pas en ligne.
3. Sinon **transcription** depuis l'audio (`transcribe.py`, WhisperX).

**Flux de données** : `pipeline.build()` écrit un dossier par morceau sous
`web/public/library/<slug>/` contenant `instrumental.mp3`, `vocals.mp3`,
`lyrics.lrc` et surtout **`karaoke.json`** (la source de vérité de l'app web :
lignes → mots → `{start, end}`). `_update_index()` régénère `library/index.json`.
L'app web lit ces fichiers ; elle n'appelle jamais Python sauf pour l'éditeur.

**Séparation des préoccupations importantes** :
- `config.py` : `detect_device()` + `build_profile()` choisissent des modèles
  selon CPU/GPU. Tout le pipeline est device-agnostique ; `--device` force le choix.
- `separate.py` **met en cache les stems** : si `instrumental.mp3`/`vocals.mp3`
  existent déjà, Demucs n'est PAS relancé (sauf `--force`). Itérer sur la synchro
  est donc rapide.
- `pipeline.py` a un **garde-fou anti-dérive** : lors d'un `--realign` par-dessus
  un LRC en ligne, si l'alignement dérive trop (`_median_drift > REALIGN_MAX_DRIFT`),
  on rejette le mot-à-mot et on garde la synchro en ligne.
- L'éditeur (`server.py`) réécrit `karaoke.json` + `lyrics.lrc` + `index.json` via
  `POST /api/save/<slug>`. Le lecteur en mode Vite (`:5173`) vise `:8765` par CORS.

**Types partagés** : `transcribe.Line` / `transcribe.Word` sont la représentation
interne commune (produite par `align`, `transcribe`, et le parsing `lrc`).

## Ce qui n'est PAS versionné

`web/public/library/<slug>/` (stems `.mp3`, `.mp4`, etc.) est **gitignoré** :
volumineux ET soumis au droit d'auteur (ne pas redistribuer les instrumentaux).
Seul `library/index.json` est suivi. `.venv/`, `web/node_modules/`, `web/dist/`,
`scripts/bin/` sont également ignorés.
