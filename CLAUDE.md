# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

**Karaokit** — karaoké maison. Un pipeline Python transforme un fichier audio
(FLAC/MP3/WAV) en karaoké (séparation voix/instru, paroles synchronisées), et une
app web React le lit. Le module Python s'importe sous le nom **`karaoke`** (le
projet s'appelle Karaokit ; commande : `uv run karaoke …` ou `uv run python -m karaoke …`).

## Contraintes d'environnement (à connaître AVANT tout)

- **Python géré par uv** (3.12) : `pyproject.toml` + `uv.lock` sont la source de
  vérité. Deux variantes exclusives : `uv sync --extra gpu` (PyTorch cu128) ou
  `uv sync --extra cpu`. Toujours lancer via `uv run …` (jamais pip / .venv/bin).
- **Pas de sudo ni de compilateur C/C++ requis** — ne pas réintroduire ces dépendances :
  - **ffmpeg** : système s'il existe, sinon build statique dans `scripts/bin/`
    (`utils.ffmpeg_bin()` cherche PATH puis `scripts/bin/`).
  - **L'alignement forcé utilise `torchaudio.pipelines.MMS_FA`** (wheel
    précompilé), PAS `ctc-forced-aligner` (compilateur C++).
- `torchaudio.forced_align` est **déprécié en 2.9** → rester en torch/torchaudio **2.8**
  (c'est aussi ce qu'exige whisperx 3.8).
- **GPU + faster-whisper/WhisperX** : ctranslate2 ne trouve pas `libcublas.so.12`
  des wheels `nvidia-*` → `utils.preload_cuda_libs()` doit être appelé avant tout
  import de faster_whisper/whisperx (déjà fait dans `verify.py` et `transcribe.py`).
- Node via **nvm** (`~/.nvm`) : `. "$HOME/.nvm/nvm.sh"`.

## Commandes

```bash
scripts/bootstrap.sh gpu        # ou cpu : ffmpeg, uv sync, nvm, npm ci + build

uv run karaoke build "morceau.flac"               # tags FLAC lus automatiquement
uv run karaoke build "/chemin/vers/Album/"        # dossier = album (modèles chargés 1 fois)
uv run karaoke build morceau.flac --line-only     # garder un LRC ligne-à-ligne tel quel
uv run karaoke build morceau.flac --realign       # ignorer les timecodes en ligne, tout ré-aligner
uv run karaoke build morceau.flac --force         # recalcule TOUT, y compris Demucs
uv run karaoke list
uv run karaoke export <slug>                      # vidéo MP4 ; 'all' pour tous
uv run karaoke serve [--library DIR]              # http://localhost:8765 : lecteur + éditeur

# Tests unitaires (logique pure)
uv run --group dev pytest tests/                  # ou : uv run python tests/test_core.py

# Test de bout en bout navigateur (Chromium headless, vrai audio)
uv run --with playwright python scripts/bench_player.py web/dist web/public/library local [--cpu 4] [--throttle 10]

# App web
cd web && npm ci
npm run dev        # :5173 (l'éditeur POST vers :8765)
npm run build      # requis avant `karaoke serve`
```

## Architecture (big picture)

Doc détaillée : [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Points qui
nécessitent de lire plusieurs fichiers :

**Dégradation en 3 niveaux pour la synchro** (cœur du projet, dans `pipeline.build`) :
1. **LRC synchronisé** trouvé en ligne (`lyrics.py` + `lrc.py`) → timecodes de
   ligne conservés, et **mot-à-mot posé dans chaque ligne** (`align.align_to_lines` :
   alignement MMS_FA dans la fenêtre de la ligne, pas de dérive possible).
2. Sinon **texte seul** trouvé → **alignement forcé** du texte sur la voix isolée
   (`align.align_lyrics`). C'est ce qui différencie Karaokit d'OpenKara.
3. Sinon **transcription** depuis l'audio (`transcribe.py`, WhisperX).

**Paroles fiables ou non** : `lyrics.fetch_lyrics` interroge d'abord LRCLIB en
direct avec la durée du morceau (`trusted=True`), puis syncedlyrics (recherche
floue, `trusted=False`). Un résultat non fiable est vérifié par `verify.py`
(transcription Whisper rapide + recouvrement de bigrammes) ; s'il ne correspond pas,
on passe au niveau 3. Le score CTC de MMS_FA ne permet PAS ce contrôle (testé).

**Flux de données** : `pipeline.build()` écrit un dossier par morceau sous
`web/public/library/<slug>/` contenant `instrumental.mp3`, `vocals.mp3`,
`lyrics.lrc` et surtout **`karaoke.json`** (la source de vérité de l'app web :
lignes → mots → `{start, end}`). `_update_index()` régénère `library/index.json`.
L'app web lit ces fichiers ; elle n'appelle jamais Python sauf pour l'éditeur.

**Séparation des préoccupations importantes** :
- `config.py` : `detect_device()` + `build_profile()` choisissent des modèles
  selon CPU/GPU. Tout le pipeline est device-agnostique ; `--device` force le choix.
- `separate.py` : Demucs **en processus** (modèle en cache), **seul le sous-modèle
  « voix »** de `htdemucs_ft` tourne (poids identité du sac → même voix, 4× plus
  rapide), **instrumental = mix − voix**, fp16 sur GPU, encodages MP3 parallèles.
  Les stems sont **mis en cache** : s'ils existent, Demucs n'est pas relancé (sauf
  `--force`) — supprimer `karaoke.json` suffit pour re-synchroniser.
- `pipeline.py` lance la recherche de paroles **en parallèle** de Demucs (album :
  toutes les recherches d'un coup) et écrit `timings` dans `karaoke.json`.
- `align._emission` découpe l'audio en tranches de 30 s (+5 s de contexte) :
  l'attention wav2vec2 est quadratique, un bloc de 7 min coûtait 13 s.
- `pipeline.py` a un **garde-fou anti-dérive** : lors d'un `--realign` par-dessus
  un LRC en ligne, si l'alignement dérive trop (`_median_drift > REALIGN_MAX_DRIFT`),
  on rejette le mot-à-mot et on garde la synchro en ligne.
- `server.py` gère **HTTP Range (206)** — sans ça le seek audio repart de 0 dans
  Chrome —, envoi en flux, keep-alive, ETag/304. L'éditeur réécrit
  `karaoke.json` + `lyrics.lrc` + `index.json` via `POST /api/save/<slug>`. Le lecteur en mode Vite (`:5173`) vise `:8765` par CORS.

**Types partagés** : `transcribe.Line` / `transcribe.Word` sont la représentation
interne commune (produite par `align`, `transcribe`, et le parsing `lrc`).

**Lecteur web** (`KaraokePlayer.jsx`) : React ne se re-rend qu'au changement de
mot (état `cursor`), l'horloge « lente » `time` est à 4 Hz, et le remplissage du mot
en cours est une **animation CSS** (durée du mot, délai négatif) — pas de JS par
image. La voix-guide n'est téléchargée que si le curseur guide > 0. Le morceau est
dans l'URL (`#/<slug>`).

## Ce qui n'est PAS versionné

`web/public/library/<slug>/` (stems `.mp3`, `.mp4`, etc.) est **gitignoré** :
volumineux ET soumis au droit d'auteur (ne pas redistribuer les instrumentaux).
Seul `library/index.json` est suivi. `.venv/`, `web/node_modules/`, `web/dist/`, `*.part.mp3`,
`scripts/bin/` sont également ignorés.
