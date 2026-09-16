# Cadrage — Karaokit

Ce document décrit le **pourquoi** : besoin, périmètre, contraintes, hypothèses et
décisions. Le **comment** est dans [ARCHITECTURE.md](ARCHITECTURE.md) ; l'étude
préalable (état de l'art, outils existants) est dans [ETUDE.md](ETUDE.md).

## Sommaire

1. [Besoin](#1-besoin)
2. [Objectifs et périmètre](#2-objectifs-et-périmètre)
3. [Contraintes](#3-contraintes)
4. [Hypothèses](#4-hypothèses)
5. [Stack technique](#5-stack-technique)
6. [Décisions](#6-décisions)
7. [Feuille de route](#7-feuille-de-route)
8. [Stratégie de tests](#8-stratégie-de-tests)
9. [Références](#9-références)

---

## 1. Besoin

Faire un karaoké **à la maison** à partir de sa propre musique (surtout des FLAC),
sans dépendre d'un catalogue en ligne. Trois capacités :

1. **Choisir un morceau** dans sa musique et le mettre dans une playlist.
2. **Obtenir la musique sans la voix**, par séparation automatique.
3. **Afficher les paroles synchronisées mot à mot**, même quand aucune synchronisation
   n'existe en ligne.

Utilisateur visé : un particulier, sur son ordinateur, avec un écran ou une TV sur le
réseau local.

---

## 2. Objectifs et périmètre

**Dans le périmètre**

| Objectif | Réalisation |
|---|---|
| Séparer voix et instrumental | Demucs, sous-modèle voix de `htdemucs_ft` |
| Récupérer les paroles | LRCLIB, puis syncedlyrics |
| Synchroniser mot à mot | Alignement forcé MMS_FA, ou transcription WhisperX |
| Refuser des paroles qui ne correspondent pas au morceau | Vérification par transcription |
| Traiter un album entier | `karaoke build <dossier>` |
| Playlist, recherche, lecture enchaînée | Application web |
| Corriger une synchronisation | Éditeur du lecteur |
| Exporter une vidéo | `karaoke export` (MP4, sous-titres ASS) |

**Hors périmètre**

- Notation du chant (hauteur, justesse) façon SingStar.
- Hébergement public ou multi-utilisateur, comptes, authentification.
- Téléchargement de musique ; seuls les fichiers déjà présents sur l'ordinateur sont traités.
- Redistribution des instrumentaux, paroles ou vidéos.

---

## 3. Contraintes

| Contrainte | Détail |
|---|---|
| Exécution | **100 % locale** ; seules les requêtes de paroles (artiste, titre, durée) sortent de la machine |
| Système | WSL2 sous Windows, **sans sudo ni compilateur C/C++** |
| Matériel de référence | NVIDIA RTX 4060 Ti 16 Go ; fonctionnement CPU conservé |
| Python | 3.12, dépendances gérées par **uv** |
| Versions figées | torch et torchaudio **2.8** (voir [ARCHITECTURE.md](ARCHITECTURE.md#8-décisions-darchitecture)) |
| Droits d'auteur | Usage personnel ; pistes générées exclues du dépôt |

---

## 4. Hypothèses

| Hypothèse | Pourquoi | Ce qui la remettrait en cause |
|---|---|---|
| Les fichiers ont des **tags** titre / artiste corrects | La recherche de paroles en dépend | Bibliothèque mal taguée : paroles introuvables, passage en transcription |
| La **durée** du fichier est celle de la version publiée | LRCLIB est interrogé avec la durée (±3 s) | Version longue, live ou remix : la fiche LRCLIB ne correspond pas |
| Un LRC communautaire a des **débuts de ligne justes à ±0,6 s** | Le mot à mot est aligné dans cette fenêtre | LRC très décalé : mots mal placés |
| La **voix séparée** est assez propre pour l'alignement et la transcription | Toute la synchronisation s'appuie dessus | Voix très noyée, chœurs dominants |
| Le serveur tourne sur un **réseau de confiance** | Aucune authentification | Exposition sur un réseau partagé ou Internet |
| Une **seule personne** gère la playlist à la fois | Pas de gestion de conflits | Soirée avec plusieurs téléphones modifiant la playlist |

---

## 5. Stack technique

| Brique | Choix | Licence |
|---|---|---|
| Séparation | Demucs 4.1.0 (`htdemucs_ft`) | MIT |
| Paroles en ligne | API LRCLIB, syncedlyrics 1.0.1 | Service gratuit / MIT |
| Alignement forcé | torchaudio 2.8.0 `MMS_FA` | BSD-2-Clause (code), à confirmer pour les poids |
| Transcription | WhisperX 3.8.6, faster-whisper 1.2.1 | BSD-2-Clause, MIT |
| Calcul | PyTorch 2.8.0 | BSD-3-Clause |
| Audio / vidéo | ffmpeg | LGPL / GPL selon la compilation |
| Serveur | Bibliothèque standard Python | PSF |
| Interface | React 18.3.1, Vite 5.4 | MIT |

---

## 6. Décisions

Les justifications détaillées et les mesures sont dans
[ARCHITECTURE.md, section 8](ARCHITECTURE.md#8-décisions-darchitecture).

**Décisions figées**

- **Synchronisation calculée depuis l'audio** plutôt que seulement téléchargée : un
  morceau absent des bases en ligne reste chantable. C'est ce qui distingue Karaokit
  d'OpenKara, qui dépend entièrement de LRCLIB.
- **Dégradation en trois niveaux** (LRC synchronisé, texte seul, transcription) plutôt
  qu'une méthode unique : on garde la meilleure source disponible.
- **Vérification des paroles floues** plutôt qu'une confiance aveugle : une recherche
  approximative peut renvoyer un autre morceau.
- **Sous-modèle voix de `htdemucs_ft`** plutôt que l'ensemble complet : même voix,
  calcul 4 fois plus court.
- **Application web locale** plutôt qu'une application de bureau : utilisable depuis
  une TV ou un téléphone du réseau, sans installation.
- **Découpage des lignes selon la source** plutôt que selon les silences : décision
  confirmée le 16/09/2026.

**À trancher**

- **Playlists multiples** — actuellement une seule playlist.
- **Titre suivant pas encore prêt** — actuellement sauté ; alternative : attendre sa préparation.
- **Écoute réseau** — `0.0.0.0` (accessible au réseau local) ou `127.0.0.1` par défaut.
- **Fichier `LICENSE`** — absent du dépôt ; licence MIT prévue.

---

## 7. Feuille de route

| Étape | Contenu | État |
|---|---|---|
| 0 | Séparation, paroles LRC, lecteur web | Fait |
| 1 | Alignement forcé du texte, transcription, éditeur de synchronisation | Fait |
| 2 | Mot à mot, pré-roll, voix guide, export vidéo, cache des pistes | Fait |
| 3 | Optimisation du pipeline, vérification des paroles, seek et fluidité du lecteur | Fait |
| 4 | Playlist, recherche dans l'ordinateur, préparation automatique, lecture enchaînée | Fait |
| 5 | Repli équilibré des lignes longues, édition mot par mot | À faire |
| 6 | Playlists nommées, réordonnancement sur mobile, sécurité réseau | À faire |

---

## 8. Stratégie de tests

| Niveau | Outil | Ce qui est prouvé |
|---|---|---|
| Unitaire | [tests/test_core.py](../tests/test_core.py), 22 tests | Formats LRC et ASS, alignement (reconstruction, interpolation, chevauchements), recherche LRCLIB, vérification par bigrammes, requêtes Range, explorateur limité aux racines, file et playlist |
| Bout en bout du lecteur | [scripts/bench_player.py](../scripts/bench_player.py) | Délai avant le premier son, seek, fluidité, précision du surlignage, voix guide, dans Chromium |
| Pipeline sur audio réel | Traitement manuel de morceaux, `timings` de `karaoke.json` | Durées de traitement, qualité des paroles et du mot à mot |

Non couvert automatiquement : le pipeline complet sur un fichier audio (dépend des
modèles et du réseau).

---

## 9. Références

| Ressource | Usage |
|---|---|
| [ETUDE.md](ETUDE.md) | Étude initiale : pipeline en 4 briques, comparatif des outils |
| [Demucs](https://github.com/facebookresearch/demucs) | Séparation voix / instrumental |
| [LRCLIB](https://lrclib.net) | Base ouverte de paroles synchronisées |
| [syncedlyrics](https://pypi.org/project/syncedlyrics/) | Recherche de paroles multi-sources |
| [WhisperX](https://github.com/m-bain/whisperX) | Transcription et alignement mot à mot |
| [OpenKara](https://github.com/thedavidweng/OpenKara) | Application karaoké la plus proche du besoin |
| [karaoke-gen](https://github.com/nomadkaraoke/karaoke-gen) | Référence pour la génération de vidéos |
