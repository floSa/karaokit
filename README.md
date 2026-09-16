# 🎤 Karaokit

**Karaoké maison : sépare, synchronise, chante.**

Transforme un fichier audio (FLAC, MP3, WAV…) en karaoké : séparation
voix/instrumental, récupération + synchronisation des paroles, et lecteur web
avec surlignage mot-à-mot.

> Le module Python s'importe sous le nom `karaoke` (`uv run karaoke …`).
>
> 🏗 Architecture interne (modules, flux de données) :
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

> 📄 Contexte, état de l'art et choix techniques : voir
> [`karaoke-maison-etude.md`](karaoke-maison-etude.md).

## État d'avancement (validé sur du vrai audio)

| Fonction | État | Détail |
|---|:---:|---|
| Séparation voix/instru (Demucs) | ✅ | ~7 s/titre sur GPU (sous-modèle voix de `htdemucs_ft`) ; stems mis en cache |
| Paroles niveau 1 (LRC synchronisé en ligne) | ✅ | LRCLIB direct avec la durée du titre, puis `syncedlyrics` ; **mot-à-mot posé dans chaque ligne** |
| Vérification des paroles trouvées | ✅ | une recherche floue qui ramène un autre morceau est rejetée (Whisper rapide) |
| Paroles niveau 2 (alignement forcé du texte) | ✅ | torchaudio **MMS_FA** ; validé : **médian 80 ms**, 19/19 lignes < 1 s |
| Paroles niveau 3 (transcription à l'aveugle) | ✅ | WhisperX si aucune parole en ligne |
| Métadonnées auto (tags FLAC) | ✅ | ffprobe ; plus besoin de `--artist/--title` |
| Traitement d'un album (dossier) | ✅ | `build <dossier>` |
| Surlignage mot-à-mot (`--realign`) | ✅ | timecodes par mot dans `karaoke.json` |
| Lecteur web (React) | ✅ | surlignage progressif, pré-roll, voix-guide, raccourcis, lien direct `#/<slug>` |
| Export vidéo MP4 (ASS `\k`) | ✅ | `export <slug>` / `export all` — 1280×720 H.264+AAC, vérifié à l'image |
| Garde-fou anti-dérive (`--realign`) | ✅ | rejette un ré-alignement qui dérive (> 1,5 s) |
| Lecteur : seek, streaming, fluidité | ✅ | HTTP Range, 1er son en ~0,2 s, remplissage du mot en CSS |
| Découpage des lignes trop longues | ✅ | niveau 3 : une ligne de 200 mots → 44 lignes |
| Ajout de morceaux depuis l'app web | ✅ | explorateur de ta musique, liste à traiter, progression en direct |
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

- **`karaoke/`** — pipeline Python (CLI `uv run karaoke`).
- **`web/`** — app web Vite + React (lecteur karaoké).
- **`scripts/bootstrap.sh`** — installe tout **sans sudo** (ffmpeg, uv, Node).
- **`scripts/bench_player.py`** — test de bout en bout du lecteur dans Chromium.

Le code est **device-agnostique** : il détecte automatiquement le GPU (CUDA) et
choisit des modèles adaptés. Dépendances dans `pyproject.toml` (uv), variantes
`--extra gpu` et `--extra cpu`.

## Installation

```bash
scripts/bootstrap.sh gpu      # carte NVIDIA — ou 'cpu'
```

> Le premier lancement télécharge les modèles (Demucs, MMS_FA, Whisper) : compte
> quelques centaines de Mo et un peu de patience. ffmpeg est trouvé automatiquement
> (système ou `scripts/bin/`).

## Utilisation

```bash
# 1) Traiter un morceau — l'artiste/titre est lu dans les tags du fichier
uv run karaoke build "morceau.flac"

# 2) Traiter un ALBUM entier (dossier) d'un coup — modèles chargés une seule fois
uv run karaoke build "/mnt/c/Users/.../Album"

# 3) Variantes de synchro
uv run karaoke build morceau.flac --line-only     # garder le LRC en ligne ligne-à-ligne
uv run karaoke build morceau.flac --realign       # ignorer les timecodes en ligne, tout ré-aligner

# 4) Lister la bibliothèque
uv run karaoke list

# 5) Exporter une vidéo karaoké MP4 (sous-titres incrustés, effet mot-à-mot)
uv run karaoke export hippie-hourrah-revenons-au-debut   # slug (voir 'list')
uv run karaoke export all

# 6a) Lecteur web + ÉDITEUR de synchro (après `cd web && npm run build`)
uv run karaoke serve               # http://localhost:8765

# 6b) Lecteur web en développement (rechargement à chaud)
cd web && npm run dev              # http://localhost:5173
```

### Ajouter des morceaux depuis l'app

`uv run karaoke serve`, puis **➕ Ajouter des morceaux** :
1. parcours ta musique (par défaut `~/Music` et `C:\Users\<toi>\Music` ; autre
   dossier : `karaoke serve --music "/chemin"`, option répétable) ;
2. coche des morceaux, ou **+ album** pour un dossier entier ; ils s'ajoutent à la
   liste **À traiter** (langue optionnelle) ;
3. **🎤 Créer les karaokés** : les morceaux sont traités un par un en arrière-plan,
   l'avancement s'affiche (séparation, paroles, synchro…) et **▶ chanter** apparaît
   dès qu'un morceau est prêt. Les morceaux déjà présents sont ignorés.

La file est en mémoire : arrêter le serveur l'annule (les morceaux terminés restent).

**Raccourcis clavier du lecteur** : `Espace` = lecture/pause · `←` / `→` = ±5 s ·
`Début` = revenir au début. Curseur « guide » pour réintroduire un peu de voix.

### Éditeur de synchro

Dans le lecteur, bouton **✎ Éditer** :
- **Décalage global** `−0,1 s` / `+0,1 s` : corrige un retard/avance systématique.
- **Caler la ligne ici** : sélectionne une ligne (clic), lance la lecture, et cale
  son départ sur l'instant courant.
- **💾 Enregistrer** : réécrit `karaoke.json` + `lyrics.lrc` via le serveur local
  (`uv run karaoke serve`). En mode `npm run dev`, l'éditeur contacte
  automatiquement le serveur sur le port 8765 (lance-le en parallèle).

## Options utiles

| Option | Effet |
|---|---|
| `--device auto\|cpu\|cuda` | Force le matériel (défaut : auto-détection). |
| `--language fr` | Force la langue (améliore transcription et alignement). |
| `--title` / `--artist` | Surcharge les métadonnées (par défaut : tags du fichier, sinon nom/arborescence). |
| `--realign` | Ignore les timecodes en ligne et ré-aligne tout le texte sur la voix (garde-fou anti-dérive). |
| `--line-only` | Garde un LRC ligne-à-ligne tel quel (pas de mot-à-mot). |
| `--force` | Tout recalcule, **y compris** Demucs (sinon les stems déjà séparés sont réutilisés). |

> **Métadonnées automatiques** : titre/artiste sont lus dans les tags du FLAC via
> ffprobe ; à défaut, déduits du nom de fichier (`01 - Titre.flac`) et de
> l'arborescence (`.../Artiste/Album/piste.flac`).
>
> **Cache** : les stems (`instrumental.mp3`, `vocals.mp3`) sont réutilisés d'un run
> à l'autre — supprimer `karaoke.json` puis relancer `build` re-synchronise sans Demucs.
> Chaque étape est chronométrée dans `karaoke.json` (`timings`).

## Comment ça marche (rappel)

1. **Séparation** — Demucs : seul le sous-modèle « voix » de `htdemucs_ft` tourne ;
   `instrumental.mp3` = mix − voix (complémentaire exact).
2. **Paroles** — LRCLIB (artiste + titre + durée), puis recherche floue
   `syncedlyrics`, lancées **en parallèle** de la séparation. Un résultat flou est
   vérifié contre la voix avant d'être utilisé.
3. **Synchro** — LRC ligne-à-ligne : mot-à-mot aligné dans chaque ligne (MMS_FA) ;
   texte seul : alignement forcé ; rien : transcription WhisperX.
4. **Affichage** — l'app web lit `karaoke.json` et remplit les mots en rythme ;
   un curseur « guide » réintroduit un peu de voix pour s'aider.

## Dépannage

- **`ffmpeg introuvable`** → installe ffmpeg ou relance `scripts/bootstrap.sh`.
- **`libcublas.so.12 is not found`** (GPU) → géré par `utils.preload_cuda_libs()` ;
  vérifie que la variante GPU est installée (`uv sync --extra gpu`).
- **CUDA plus ancienne que 12.8** → adapte l'index `pytorch-cu128` dans `pyproject.toml`
  (voir <https://pytorch.org/get-started/locally/>).
- **Paroles fausses/décalées** → relance avec `--language`, `--realign`, ou
  corrige à la main dans l'éditeur du lecteur (`uv run karaoke serve`).
