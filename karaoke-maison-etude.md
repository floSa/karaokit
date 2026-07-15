# Karaoké maison — étude technique & feuille de route

> Objectif : à partir d'un fichier musical (FLAC surtout), séparer voix/musique,
> récupérer le texte des paroles, les synchroniser, et afficher un karaoké.

---

## 1. Le pipeline en 4 briques

Tout projet de karaoké automatique se décompose toujours en 4 étapes :

```
  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐   ┌──────────────┐
  │ 1. SÉPARATION│   │ 2. PAROLES   │   │ 3. SYNCHRO      │   │ 4. AFFICHAGE │
  │ voix / instru│──▶│ texte brut   │──▶│ timestamps      │──▶│ lecture +    │
  │ (stems)      │   │ (transcript  │   │ mot-à-mot / ligne│   │ surlignage   │
  │              │   │  ou base en  │   │ (forced align.) │   │ karaoké      │
  │              │   │  ligne)      │   │                 │   │              │
  └──────────────┘   └──────────────┘   └────────────────┘   └──────────────┘
        Demucs           Whisper /           WhisperX /          Web (LRC/ASS)
        UVR / RoFormer   LRCLIB /            whisper-timestamped  UltraStar /
                         syncedlyrics        AudioShake           ffmpeg vidéo
```

L'étape 1 (séparer la voix) sert **surtout à créer la piste instrumentale** (le
« backing track » qu'on chante par-dessus). La piste **voix isolée** sert surtout
à mieux transcrire/synchroniser les paroles (moins de musique = ASR plus précis).

---

## 2. Projets existants (à réutiliser ou s'inspirer)

Avant de partir de zéro, plusieurs projets open-source font déjà tout ou partie du travail.

| Projet | Ce qu'il fait | Techno | Licence | Pertinence pour toi |
|---|---|---|---|---|
| **[OpenKara](https://github.com/thedavidweng/OpenKara)** | App **desktop** karaoké clé en main : sépare les stems **on-device** (Demucs v4 en ONNX), récupère les paroles synchronisées depuis LRCLIB, mixeur 4 pistes, plein écran | Tauri 2 (Rust) + React/TS, SQLite | Apache-2.0 | ⭐ **Le plus proche de ton besoin** — à tester en premier, éventuellement à forker |
| **[karaoke-gen](https://github.com/nomadkaraoke/karaoke-gen)** (Nomad Karaoke) | Pipeline **complet et automatisé** : sépare (MDX + Demucs), transcrit (Whisper / AudioShake), matche contre Genius/Musixmatch, corrige avec LLM, **génère des vidéos karaoké 4K / CDG** | Python 3.10-3.13, PyTorch, FFmpeg, FastAPI | MIT | ⭐ Référence pour la **génération de vidéos** et l'auto-correction des paroles |
| **[python-lyrics-transcriber](https://github.com/nomadkaraoke/python-lyrics-transcriber)** | Brique « paroles synchronisées » de Nomad : produit du **LRC + ASS mot-à-mot**, avec Whisper + sources en ligne + LLM pour corriger | Python | MIT | ⭐ Bibliothèque réutilisable pour l'étape 2+3 |
| **[karaok-AI](https://github.com/EtienneAb3d/karaok-AI)** | Player/éditeur karaoké avec extraction voix + speech-to-text, découpage en clips | Python | — | Éditeur pour corriger la synchro à la main |
| **[UltraStar Deluxe](https://github.com/UltraStar-Deluxe/USDX)** / **[Performous](https://performous.org)** | **Jeux** de karaoké matures (façon SingStar, avec notation du pitch au micro) | Pascal/SDL2, C++ | GPL | Si tu veux le côté « jeu » + notation. Format `.txt` UltraStar bien documenté |

**Recommandation** : commence par **installer OpenKara** pour voir ce qu'un bon
résultat donne, et regarde **karaoke-gen / python-lyrics-transcriber** pour le
code de référence. Tu sauras vite si un fork/adaptation te suffit ou si tu veux
construire ton propre pipeline (plus formateur).

### Comparatif face aux 3 contraintes du projet

Les 3 besoins exprimés :
1. **Sélectionner un fichier** — parcourir sa bibliothèque et choisir un morceau.
2. **Musique sans les paroles** — séparer / retirer la voix.
3. **Synchroniser les paroles** à la musique.

| Solution | 1. Sélection biblio | 2. Musique sans paroles | 3. Synchro paroles | Verdict |
|---|:---:|:---:|:---:|---|
| **🏠 Notre MVP maison** | ✅ liste web cliquable | ✅ Demucs (voix/instru) | ✅ LRC en ligne, sinon WhisperX | **Les 3 ✅** |
| **OpenKara** (desktop) | ✅ bibliothèque locale | ✅ Demucs on-device | ⚠️ ✅ **seulement si** LRCLIB a le LRC (ne synchronise pas depuis l'audio) | 2,5 / 3 |
| **karaoke-gen** (Nomad) | ⚠️ générateur, pas un navigateur de biblio | ✅ MDX + Demucs | ✅ Whisper / AudioShake | 2,5 / 3 |
| **karaok-AI** | ✅ player/éditeur | ✅ extraction voix | ✅ speech-to-text + éditeur | **Les 3 ✅** |
| **python-lyrics-transcriber** | ❌ (c'est une lib) | ❌ ne sépare pas | ✅ Whisper + alignement | 1 / 3 |
| **UltraStar Deluxe / Performous** | ✅ sélection de morceaux | ❌ n'extrait pas la voix | ❌ lit des fichiers déjà synchronisés (ne les crée pas) | 1 / 3 |
| **UVR / Demucs (seuls)** | ❌ | ✅ excellente séparation | ❌ | 1 / 3 |
| **syncedlyrics / LRCLIB (seuls)** | ❌ | ❌ | ✅ fournit du LRC synchronisé | 1 / 3 |

*Légende : ✅ couvert · ⚠️ partiel/conditionnel · ❌ non couvert.*

**À retenir :** aucun outil pris **seul** ne coche les 3 cases — chacun ne fait
qu'une brique, d'où l'intérêt d'assembler un pipeline. Deux options couvrent les
3 besoins : **notre MVP maison** et **karaok-AI**.

#### Le cas OpenKara : synchro « téléchargée » vs synchro « calculée »

OpenKara est très proche du besoin mais sa synchro est en ⚠️ pour une raison
importante. Il y a **deux façons** d'obtenir des paroles synchronisées :

- **A. Télécharger une synchro déjà faite** — OpenKara va chercher sur **LRCLIB**
  un fichier `.lrc` que **quelqu'un a déjà créé et déposé** en ligne. Il ne fait
  que le *récupérer*. Donc :
  - ✅ le morceau est dans LRCLIB avec timecodes → karaoké parfait, instantané ;
  - ⚠️ paroles présentes **sans** timecodes → le texte s'affiche mais ne défile pas ;
  - ❌ morceau absent de LRCLIB (titre obscur, live, remix, démo perso) → rien.
  OpenKara **n'écoute jamais l'audio** pour calculer le timing : il dépend à 100 %
  de ce que la communauté a déposé en ligne.
- **B. Calculer la synchro depuis l'audio** (*forced alignment*) — le logiciel
  écoute la **voix isolée** et détermine lui-même à quelle milliseconde chaque mot
  est chanté (WhisperX/wav2vec2). Ça marche **même si le morceau n'existe nulle
  part en ligne**.

**Notre MVP fait les deux, dans l'ordre :** (1) il tente d'abord LRCLIB (raccourci
gratuit et parfait quand il existe), puis (2) **s'il n'y a pas de LRC synchronisé,
il fabrique la synchro** avec WhisperX à partir de la piste voix. C'est
exactement le trou que notre solution comble par rapport à OpenKara : on n'est
jamais bloqué par l'absence du morceau dans une base en ligne.

---

## 3. Brique 1 — Séparation voix / musique

L'état de l'art repose sur des réseaux de neurones. Trois familles reviennent :

### Modèles / outils
- **Demucs v4** (Meta, [github](https://github.com/facebookresearch/demucs)) —
  *Hybrid Transformer Demucs*. Le standard open-source, excellent, sépare en
  4 stems (voix, basse, batterie, autres) ou en 2 (voix / accompagnement).
  Modèle `htdemucs_ft` = version fine-tunée, meilleure qualité mais plus lente.
  Utilisable en une ligne : `demucs --two-stems=vocals morceau.flac`.
- **RoFormer** (BS-RoFormer / Mel-RoFormer) — famille la plus récente (2024-2025),
  souvent citée comme **la plus propre** pour un split voix/instru en un clic.
- **MDX-Net** — très bon pour des instrumentaux ultra-propres, souvent combiné
  à Demucs en **ensemble** pour le top qualité.
- **[UVR — Ultimate Vocal Remover](https://ultimatevocalremover.com/)** — **GUI**
  gratuite qui fait tourner tous ces modèles (Demucs, MDX-Net, RoFormer) en local.
  Idéal pour **tester la qualité sans coder** et choisir ton modèle.

### Recommandation
- **Pour tester/choisir** : installe **UVR**, essaie le preset RoFormer
  (« Music & Vocals »), et si des résidus de voix subsistent, MDX-Net Voc_FT.
- **Pour automatiser** : **Demucs en ligne de commande** (Python), c'est le plus
  simple à scripter et la qualité est excellente. `--two-stems=vocals` suffit
  pour le karaoké (tu obtiens `vocals.wav` + `no_vocals.wav`).
- **GPU recommandé** (CUDA) : sur CPU ça marche mais c'est lent (plusieurs
  minutes par morceau). Sur GPU, quelques secondes à ~1 min.
- **FLAC** : parfait, c'est du lossless. Les modèles travaillent en interne à
  44.1 kHz ; ta source FLAC donnera le meilleur résultat possible.

---

## 4. Brique 2 — Récupérer le texte des paroles

Deux stratégies, **complémentaires** :

### A. Depuis une source en ligne (le plus fiable pour le TEXTE)
Récupérer des paroles déjà écrites (et parfois déjà synchronisées !).

- **[syncedlyrics](https://pypi.org/project/syncedlyrics/)** (Python) — LA lib à
  connaître. Cherche par titre+artiste sur **Musixmatch, Deezer, LRCLIB, NetEase,
  Megalobiz, Genius**. Peut retourner directement du **LRC synchronisé** (ligne
  par ligne), et même de l'**Enhanced LRC mot-à-mot** (karaoké) quand dispo.
- **[LRCLIB](https://lrclib.net)** — base ouverte, gratuite, sans clé API, de
  paroles synchronisées `.lrc`. C'est ce qu'utilise OpenKara.

👉 **Le raccourci en or** : si LRCLIB/Musixmatch a déjà le LRC synchronisé du
morceau, **les étapes 2 ET 3 sont réglées d'un coup** — tu n'as plus qu'à
afficher. À tenter **systématiquement en premier**.

### B. Depuis l'audio (quand aucune source, ou pour la synchro fine)
Transcription automatique (ASR) de la **piste voix isolée** (issue de l'étape 1).

- **[Whisper](https://github.com/openai/whisper)** (OpenAI) — ASR multilingue de
  référence. Bon en français. Attention : conçu pour la parole, **le chant est
  plus dur** (voix tenues, mélisme, chœurs) → d'où l'intérêt de le nourrir avec
  la piste voix **séparée**.
- **[whisper-timestamped](https://github.com/linto-ai/whisper-timestamped)** —
  Whisper avec timestamps mot-à-mot.

### Recommandation
1. Essayer **syncedlyrics** (texte + éventuellement déjà synchronisé).
2. Sinon (ou pour corriger), transcrire la **piste voix** avec Whisper.
3. **Idéalement combiner** : prendre le **texte propre** de la source en ligne et
   le **caler** sur l'audio (étape 3) — c'est exactement ce que fait
   python-lyrics-transcriber (texte fiable + timing réel + LLM pour arbitrer).

---

## 5. Brique 3 — Synchronisation (forced alignment)

But : associer à **chaque mot/ligne** un `début`/`fin` en millisecondes.

- **[WhisperX](https://github.com/m-bain/whisperX)** — LE choix. Pipeline en 3
  temps : Faster-Whisper (transcription) → **forced alignment wav2vec2**
  (timestamps mot-à-mot **< 100 ms**, suffisant pour surligner en karaoké) →
  diarisation optionnelle. Sort en SRT/VTT/JSON.
- **Forced alignment avec transcript fixe** : si tu as déjà le **bon texte**
  (source en ligne), tu peux forcer l'alignement de CE texte sur l'audio plutôt
  que de laisser Whisper deviner les mots → bien plus précis. (Voir
  Montreal Forced Aligner, ou l'alignement wav2vec2 de WhisperX alimenté par ton
  texte.)
- **Précision** : viser < 100 ms pour un ressenti « pro ». Ligne-par-ligne suffit
  pour un karaoké basique ; **mot-à-mot** pour le surlignage progressif type
  « bille qui saute ».

### Formats de sortie à produire
- **LRC** — simple, ligne par ligne (`[00:12.34] Paroles ici`). Enhanced LRC =
  timings mot-à-mot. Universellement lu.
- **ASS** (SubStation Alpha) — sous-titres riches avec **effets karaoké natifs**
  (`\k`, remplissage progressif du texte). C'est le format pour faire de belles
  **vidéos** karaoké via FFmpeg.
- **`.txt` UltraStar** — si tu vises les jeux UltraStar/Performous.

---

## 6. Brique 4 — Affichage du karaoké

Trois options selon l'ambition :

### Option A — Réutiliser un player existant (le plus rapide)
- **OpenKara** : lit déjà tes fichiers locaux + LRCLIB, plein écran, mixeur.
- Tout lecteur audio lisant le **LRC** (foobar2000, MPD+ncmpcpp, etc.) affiche
  déjà les paroles synchronisées basiques.

### Option B — Générer une vidéo karaoké (simple à distribuer)
- Produire un **ASS** (mot-à-mot) puis **brûler** les sous-titres sur la piste
  instrumentale avec **FFmpeg** :
  `ffmpeg -i instru.wav -vf "ass=paroles.ass" -c:a aac karaoke.mp4`
- Avantage : le résultat est une simple vidéo MP4 lisible partout (TV, téléphone).
  C'est l'approche de **karaoke-gen** (jusqu'au 4K / format CDG).

### Option C — App web maison (le plus flexible et formateur)
- Un lecteur **HTML5 `<audio>`** + un moteur JS qui lit le **LRC/JSON** et
  surligne les mots en fonction de `audio.currentTime`.
- Stack simple : Vite + React (ou même vanilla JS). Le surlignage mot-à-mot est
  juste du CSS piloté par les timestamps.
- Bonus : mixeur (2 sliders voix/instru via 2 balises `<audio>` synchronisées) —
  permet de remettre un peu de voix pour s'aider, comme OpenKara.

### Recommandation
Pour un **projet maison** : **Option C** (app web) — c'est le plus satisfaisant à
construire, portable, et tu contrôles tout l'affichage. Garde l'**Option B**
(vidéo FFmpeg) comme moyen simple d'exporter/partager un morceau fini.

---

## 7. Architecture maison recommandée

### MVP (week-end) — valider la chaîne de bout en bout
1. `demucs --two-stems=vocals morceau.flac` → `no_vocals.wav` + `vocals.wav`.
2. `syncedlyrics "Titre Artiste"` → tenter de récupérer un **LRC déjà synchro**.
3. Si LRC trouvé → petit **lecteur web** (HTML/JS) : joue `no_vocals.wav` +
   affiche/surligne le LRC. **Karaoké fonctionnel.**

### V1 — quand il n'y a pas de LRC tout prêt
4. Récupérer le **texte** via syncedlyrics (paroles brutes, non synchro).
5. **Aligner** ce texte sur `vocals.wav` avec **WhisperX** (forced alignment) →
   générer un **LRC/JSON mot-à-mot**.
6. Petit **éditeur** de correction (décaler une ligne, ajuster un mot).

### V2 — confort & qualité
7. Surlignage **mot-à-mot** progressif, pré-roll (compte à rebours avant l'entrée
   du chant), mixeur voix/instru, bibliothèque de morceaux (SQLite).
8. Export **vidéo** ASS+FFmpeg pour partager.
9. Cache : stocker stems + LRC par morceau pour ne pas recalculer.

### Stack technique concrète (proposition)
- **Langage pipeline** : **Python** (Demucs, WhisperX, syncedlyrics vivent tous
  en Python — écosystème idéal).
- **Orchestration** : un script/CLI `karaoke <fichier.flac>` qui enchaîne les
  étapes et dépose `stems/` + `paroles.lrc` dans un dossier par morceau.
- **Affichage** : app web **Vite + React** (ou vanilla) lisant les fichiers
  produits. Alternative desktop : **Tauri** (comme OpenKara) si tu veux un `.exe`.
- **Dépendances système** : **FFmpeg** (indispensable), **PyTorch** (idéalement
  avec CUDA si tu as un GPU NVIDIA — sinon CPU).
- **Matériel** : un **GPU** accélère énormément Demucs + WhisperX. Sans GPU, tout
  marche mais compte quelques minutes par morceau.

---

## 8. Points d'attention

- **Qualité du chant vs Whisper** : le chant (mélisme, voix tenues, chœurs) est
  plus dur que la parole → **toujours** transcrire la piste **voix séparée**, et
  privilégier un **texte de référence en ligne** aligné par forced-alignment
  plutôt qu'une transcription 100 % automatique.
- **Le raccourci LRCLIB** : beaucoup de morceaux connus ont déjà un LRC synchro →
  teste-le en premier, ça peut t'éviter 80 % du travail.
- **Langues** : Whisper/WhisperX gèrent bien le français et l'anglais ; pense à
  forcer la langue pour de meilleurs résultats.
- **Performances** : mets en cache les stems (fichiers lourds) et les LRC ; ne
  recalcule jamais deux fois le même morceau.
- **Aspect légal** : pour un **usage strictement personnel/maison**, tu manipules
  des fichiers que tu possèdes. Attention en revanche à **ne pas redistribuer**
  publiquement les instrumentaux, paroles ou vidéos générées (droits d'auteur sur
  la musique **et** sur les paroles). Les paroles récupérées via des API tierces
  ont aussi leurs propres conditions d'usage.

---

## 9. Liens utiles (récapitulatif)

**Projets complets**
- OpenKara — https://github.com/thedavidweng/OpenKara
- karaoke-gen (Nomad) — https://github.com/nomadkaraoke/karaoke-gen
- python-lyrics-transcriber — https://github.com/nomadkaraoke/python-lyrics-transcriber
- karaok-AI — https://github.com/EtienneAb3d/karaok-AI

**Séparation**
- Demucs — https://github.com/facebookresearch/demucs
- Ultimate Vocal Remover (GUI) — https://ultimatevocalremover.com/

**Paroles**
- syncedlyrics — https://pypi.org/project/syncedlyrics/
- LRCLIB — https://lrclib.net

**Transcription / synchro**
- Whisper — https://github.com/openai/whisper
- WhisperX — https://github.com/m-bain/whisperX
- whisper-timestamped — https://github.com/linto-ai/whisper-timestamped

**Affichage / jeux**
- UltraStar Deluxe — https://github.com/UltraStar-Deluxe/USDX
- Performous — https://performous.org
