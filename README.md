# 🎤 Karaokit

**Karaoké maison : sépare, synchronise, chante.**

Transforme un fichier audio (FLAC, MP3, WAV…) en karaoké : séparation
voix/instrumental, récupération + synchronisation des paroles, et lecteur web
avec surlignage mot-à-mot.

> Le module Python s'importe sous le nom `karaoke` (`python -m karaoke …`).

> 📄 Contexte, état de l'art et choix techniques : voir
> [`karaoke-maison-etude.md`](karaoke-maison-etude.md).

## État d'avancement (validé sur du vrai audio)

| Fonction | État | Détail |
|---|:---:|---|
| Séparation voix/instru (Demucs) | ✅ | ~90 s/titre en CPU ; stems mis en cache |
| Paroles niveau 1 (LRC synchronisé en ligne) | ✅ | via `syncedlyrics` (LRCLIB, Musixmatch, Genius…) |
| Paroles niveau 2 (alignement forcé du texte) | ✅ | torchaudio **MMS_FA** ; validé : **médian 80 ms**, 19/19 lignes < 1 s |
| Paroles niveau 3 (transcription à l'aveugle) | ✅ | WhisperX si aucune parole en ligne |
| Métadonnées auto (tags FLAC) | ✅ | ffprobe ; plus besoin de `--artist/--title` |
| Traitement d'un album (dossier) | ✅ | `build <dossier>` |
| Surlignage mot-à-mot (`--realign`) | ✅ | timecodes par mot dans `karaoke.json` |
| Lecteur web (React) | ✅ | surlignage, pré-roll, mixeur guide, raccourcis clavier |
| Export vidéo MP4 (ASS `\k`) | ✅ | `export <slug>` / `export all` — 1280×720 H.264+AAC, vérifié à l'image |
| Garde-fou anti-dérive (`--realign`) | ✅ | rejette un ré-alignement qui dérive (> 1,5 s) |
| Découpage des lignes trop longues | ✅ | niveau 3 : une ligne de 200 mots → 44 lignes |
| Éditeur de synchro (décalage + « caler ici ») | ✅ | serveur `serve` (stdlib) ; sauvegarde JSON/LRC vérifiée |

Reste à explorer : correction LLM des cas tordus (refrains/ad-libs), détection auto
de la langue par morceau, éditeur mot-à-mot fin.

## Architecture

```
Fichier audio  ─▶  [1] Séparation (Demucs)  ─▶  instrumental + voix isolée
                   [2] Paroles en ligne (syncedlyrics / LRCLIB)
                   [3] Synchro (WhisperX, si pas déjà synchronisé)
                   [4] Sorties  ─▶  web/public/library/<morceau>/
                                       ├─ instrumental.mp3
                                       ├─ vocals.mp3
                                       ├─ lyrics.lrc
                                       └─ karaoke.json   (mots + timestamps)
                                             │
                        App web React  ◀─────┘  (lecteur + surlignage)
```

- **`karaoke/`** — pipeline Python (CLI `python -m karaoke`).
- **`web/`** — app web Vite + React (lecteur karaoké).
- **`scripts/bootstrap.sh`** — installe tout **sans sudo** (ffmpeg, Node, venv).

Le code est **device-agnostique** : il détecte automatiquement le GPU (CUDA) et
choisit des modèles adaptés. Deux jeux de dépendances : `requirements-cpu.txt` et
`requirements-gpu.txt`.

## Installation

```bash
# Variante CPU (défaut) — ou 'gpu' si tu as une carte NVIDIA
scripts/bootstrap.sh cpu

# ffmpeg local dans le PATH pour la session (si installé par le script)
export PATH="$PWD/scripts/bin:$PATH"
```

> Le premier lancement télécharge les modèles (Demucs, WhisperX) : compte
> quelques centaines de Mo et un peu de patience.

## Utilisation

```bash
source .venv/bin/activate
export PATH="$PWD/scripts/bin:$PATH"      # ffmpeg local

# 1) Traiter un morceau — l'artiste/titre est lu dans les tags du fichier
python -m karaoke build "morceau.flac"
python -m karaoke build morceau.flac --language fr

# 2) Traiter un ALBUM entier (dossier) d'un coup
python -m karaoke build "/mnt/c/Users/.../Album"

# 3) Forcer le mot-à-mot (alignement sur la voix) même si un LRC existe déjà
python -m karaoke build morceau.flac --realign --language fr

# 4) Lister la bibliothèque
python -m karaoke list

# 5) Exporter une vidéo karaoké MP4 (sous-titres incrustés, effet mot-à-mot)
python -m karaoke export hippie-hourrah-revenons-au-debut   # slug (voir 'list')
python -m karaoke export all                                # tous les morceaux

# 6a) Lecteur web en développement (rechargement à chaud)
cd web && npm run dev              # http://localhost:5173

# 6b) Lecteur web + ÉDITEUR de synchro (sauvegarde locale) — nécessite un build
cd web && npm run build && cd ..
python -m karaoke serve            # http://localhost:8765
```

**Raccourcis clavier du lecteur** : `Espace` = lecture/pause · `←` / `→` = ±5 s ·
`Début` = revenir au début. Curseur « guide » pour réintroduire un peu de voix.

### Éditeur de synchro

Dans le lecteur, bouton **✎ Éditer** :
- **Décalage global** `−0,1 s` / `+0,1 s` : corrige un retard/avance systématique.
- **Caler la ligne ici** : sélectionne une ligne (clic), lance la lecture, et cale
  son départ sur l'instant courant.
- **💾 Enregistrer** : réécrit `karaoke.json` + `lyrics.lrc` via le serveur local
  (`python -m karaoke serve`). En mode `npm run dev`, l'éditeur contacte
  automatiquement le serveur sur le port 8765 (lance-le en parallèle).

## Options utiles

| Option | Effet |
|---|---|
| `--device auto\|cpu\|cuda` | Force le matériel (défaut : auto-détection). |
| `--language fr` | Force la langue (améliore transcription et alignement). |
| `--title` / `--artist` | Surcharge les métadonnées (par défaut : tags du fichier, sinon nom/arborescence). |
| `--realign` | Force le niveau 2 (alignement mot-à-mot sur la voix), même si un LRC synchronisé existe en ligne. |
| `--force` | Tout recalcule, **y compris** Demucs (sinon les stems déjà séparés sont réutilisés). |

> **Métadonnées automatiques** : titre/artiste sont lus dans les tags du FLAC via
> ffprobe ; à défaut, déduits du nom de fichier (`01 - Titre.flac`) et de
> l'arborescence (`.../Artiste/Album/piste.flac`).
>
> **Cache** : les stems (`instrumental.mp3`, `vocals.mp3`) sont réutilisés d'un run
> à l'autre — pratique pour itérer sur la synchro sans relancer Demucs.

## Comment ça marche (rappel)

1. **Séparation** — Demucs (`--two-stems=vocals`) : `instrumental.mp3` (à chanter)
   + `vocals.mp3` (sert à la synchro).
2. **Paroles** — `syncedlyrics` cherche un LRC déjà synchronisé (LRCLIB,
   Musixmatch…). Si trouvé, la synchro est offerte.
3. **Synchro** — sinon, WhisperX transcrit la voix isolée et aligne chaque mot
   (< 100 ms).
4. **Affichage** — l'app web lit `karaoke.json` et surligne les mots en rythme ;
   un curseur « guide » réintroduit un peu de voix pour s'aider.

## Dépannage

- **`ffmpeg introuvable`** → `export PATH="$PWD/scripts/bin:$PATH"` ou installe ffmpeg.
- **Installation torch/whisperx capricieuse** → vérifie ta version de CUDA et
  adapte l'`--extra-index-url` dans `requirements-gpu.txt`
  (voir <https://pytorch.org/get-started/locally/>).
- **Paroles fausses/décalées** → relance avec `--language`, ou édite le `.lrc`
  à la main (prochaine étape : un petit éditeur de synchro).
```
