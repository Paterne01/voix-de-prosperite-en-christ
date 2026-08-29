# OPENCODE — Voix de Prospérité en Christ : Viral Engine v2
# Instructions modulaires pour Muse Spark 1.2 (free)
# Paterne — i5-2520M, 8 Go RAM, Intel HD 3000, Windows, NO GPU
# Budget : $0 — outils gratuits uniquement

---

## COMMENT UTILISER CE DOCUMENT

Ce fichier contient 8 TÂCHES INDÉPENDANTES.
Envoie chaque tâche à OpenCode dans une session séparée.
Commence toujours par coller le CONTEXTE GLOBAL, puis la tâche.
Implémente dans l'ordre des numéros (priorité décroissante).

---

## CONTEXTE GLOBAL (à coller en tête de chaque session OpenCode)

```
Tu travailles sur "Voix de Prospérité en Christ" — une app de bureau Windows,
Python 3.12, Flask, SQLite, FFmpeg, APScheduler.
Structure du projet :
  src/content.py        → génération Format A (Shorts vidéo, 60s max)
  src/content_declarations.py → génération Format B (images déclarations)
  src/video.py          → pipeline FFmpeg (Ken Burns, overlay, intro/outro)
  src/images.py         → génération images
  src/service.py        → logique de publication (Facebook Graph API v25, YouTube Data API)
  src/database.py       → SQLite (posts, overlays, scheduled_posts)
  src/manual_scheduler.py → Format C (vidéos manuelles)
  app.py                → Flask routes
  config.json           → chemins, réseaux par format
  assets/format_a/audio/  → musiques de fond Format A
  assets/format_c/audio/  → musiques de fond Format C

PC cible : Intel Core i5-2520M (4 threads), 8 Go RAM, Intel HD Graphics 3000,
NO GPU. FFmpeg doit utiliser uniquement le CPU (-c:v libx264).

Contraintes absolues :
- Aucune bibliothèque payante
- Aucun cloud payant
- Pas de torch/tensorflow/sklearn
- SQLite uniquement (pas de PostgreSQL)
- Compatibilité Windows (pas de fork/multiprocessing complexe)
- L'interface Flask existante doit rester fonctionnelle
```

---

## TÂCHE 1 — ANTI-SHADOWBAN (URGENT — faire en premier)

### Problème
L'app publie 6 posts/jour via API à heures fixes → détecté comme bot par Facebook.
Résultat : shadowban de page (tous les anciens posts ont aussi perdu leur reach).

### Objectif
Réduire à 2-3 posts/jour max et ajouter un délai aléatoire sur chaque publication.

### Instructions pour OpenCode

```
CONTEXTE : [coller le contexte global ci-dessus]

TÂCHE 1 — ANTI-SHADOWBAN

Modifie le système de scheduling dans src/service.py et/ou app.py pour :

1. DÉLAI ALÉATOIRE : Avant chaque appel API de publication (Facebook ou YouTube),
   ajouter un délai aléatoire entre 5 et 25 minutes, tiré uniformément.
   Utilise : import random; import time; time.sleep(random.randint(300, 1500))
   Ce délai doit apparaître dans les logs : "Délai anti-bot : X secondes"

2. LIMITE FRÉQUENCE : Ajouter une vérification dans la fonction de publication.
   Avant de publier, compter les posts publiés aujourd'hui dans la table `posts`
   (colonne published_at de type TEXT format ISO). Si count >= 3, logguer
   "Limite journalière atteinte (3/3)" et ne pas publier.
   Rendre cette limite configurable dans config.json : {"max_posts_per_day": 3}

3. VARIATION HORAIRES : Dans config.json, remplacer les horaires fixes
   (08:00, 12:00, 16:00, 20:00, etc.) par des plages :
   {"schedule_windows": ["07:30-08:30", "12:00-13:00", "18:00-19:30"]}
   APScheduler doit tirer un moment aléatoire dans chaque plage au lancement.
   Implémenter une fonction pick_random_time_in_window(window_str) -> datetime.

4. Ajouter dans la table `posts` (ou créer une table `publish_log`) :
   - publish_delay_seconds INTEGER (délai appliqué)
   - publish_attempted_at TEXT (moment de la tentative)

5. Ajouter une route Flask GET /api/today-stats retournant :
   {"posts_today": N, "limit": 3, "next_window": "18:00-19:30"}

Ne touche pas à la logique de génération de contenu.
Teste en lançant app.py et en vérifiant les logs.
```

---

## TÂCHE 2 — EDGE-TTS : VOIX HUMAINE GRATUITE SUR FORMAT A

### Problème
Format A = vidéos Ken Burns sans voix = détectable comme contenu automatisé.
Rétention YouTube Shorts très faible sans narration.

### Objectif
Ajouter une voix neural française (Microsoft Edge-TTS, gratuit, sans GPU)
sur chaque Short Format A généré.

### Instructions pour OpenCode

```
CONTEXTE : [coller le contexte global ci-dessus]

TÂCHE 2 — VOIX EDGE-TTS SUR FORMAT A

Installation requise (à lancer une fois) :
  pip install edge-tts

1. Crée un nouveau fichier src/tts.py avec :

   import asyncio
   import edge_tts
   import os

   VOICE = "fr-FR-HenriNeural"  # Voix masculine francophone professionnelle
   # Alternative féminine : "fr-FR-DeniseNeural"

   async def generate_voice(text: str, output_path: str) -> str:
       """Génère un fichier audio MP3 depuis du texte. Retourne le chemin."""
       communicate = edge_tts.Communicate(text, VOICE)
       await communicate.save(output_path)
       return output_path

   def text_to_speech(text: str, output_path: str) -> str:
       """Wrapper synchrone pour generate_voice."""
       asyncio.run(generate_voice(text, output_path))
       return output_path

   def build_narration_text(content: dict) -> str:
       """
       Construit le texte de narration depuis le contenu généré.
       content doit avoir : hook, points (list of {heading, body, application}),
       truth, cta, verse_reference
       Retourne une narration orale naturelle, max 55 secondes de parole.
       """
       parts = []
       if content.get("hook"):
           parts.append(content["hook"])
       for point in content.get("points", [])[:3]:  # max 3 points pour tenir en 55s
           if point.get("heading"):
               parts.append(point["heading"] + ".")
           if point.get("application"):
               parts.append(point["application"])
       if content.get("truth"):
           parts.append(content["truth"])
       if content.get("cta"):
           parts.append(content["cta"])
       return " ".join(parts)


2. Dans src/video.py, modifie la fonction principale de génération Format A
   (cherche la fonction qui appelle FFmpeg pour Ken Burns) :

   a. Après la génération du contenu (content dict disponible), appeler :
      from src.tts import text_to_speech, build_narration_text
      narration_text = build_narration_text(content)
      voice_path = text_to_speech(narration_text, "temp_voice.mp3")

   b. Dans la commande FFmpeg de mixage audio, ajouter la piste voix :
      AVANT (musique seule) :
        -i assets/format_a/audio/xxx.mp3
        -filter_complex "[1:a]volume=0.6[music]; [music]"

      APRÈS (voix + musique en fond) :
        -i assets/format_a/audio/xxx.mp3
        -i temp_voice.mp3
        -filter_complex "
          [1:a]volume=0.15,aloop=loop=-1:size=2e+09[music];
          [2:a]volume=1.0[voice];
          [music][voice]amix=inputs=2:duration=longest[audio]
        "
        -map "[audio]"
      NOTE : la musique passe à 0.15 (fond), la voix à 1.0 (premier plan).

   c. Ajouter dans config.json :
      {"tts_enabled": true, "tts_voice": "fr-FR-HenriNeural"}
      Si tts_enabled = false, utiliser l'ancien comportement (musique seule).

   d. Nettoyer temp_voice.mp3 après la génération de la vidéo.

3. Dans l'interface Flask (templates/index.html), ajouter une checkbox
   "Voix activée (TTS)" qui toggle tts_enabled dans config.json via
   une route POST /api/config/tts.

FFmpeg doit rester CPU uniquement (-c:v libx264 -preset veryfast -crf 28 -threads 4).
Tester avec un appel force-publish Format A et vérifier que la vidéo a une voix.
```

---

## TÂCHE 3 — ENDPOINT FACEBOOK REELS (portée x10)

### Problème
L'app publie probablement via /me/videos (portée limitée aux abonnés).
/me/reels distribue aux non-abonnés via l'algorithme Facebook.

### Objectif
Migrer les publications vidéo Format A vers l'endpoint Reels de Graph API v25.

### Instructions pour OpenCode

```
CONTEXTE : [coller le contexte global ci-dessus]

TÂCHE 3 — ENDPOINT FACEBOOK REELS

Dans src/service.py, cherche toutes les occurrences d'appels à l'API Facebook
pour publier des vidéos (cherche : /videos, graph.facebook.com, me/videos).

1. ENDPOINT REELS : Remplacer l'upload vidéo pour Format A par le protocole Reels.
   L'API Facebook Reels v25 utilise un upload en 3 étapes :

   Étape 1 — Initialisation :
   POST https://graph.facebook.com/v25.0/{PAGE_ID}/video_reels
   params: {"upload_phase": "start", "access_token": TOKEN}
   → Retourne {"video_id": "xxx", "upload_url": "yyy"}

   Étape 2 — Upload binaire :
   POST {upload_url}
   headers: {
     "Authorization": f"OAuth {TOKEN}",
     "offset": "0",
     "file_size": str(file_size_bytes)
   }
   data: open(video_path, "rb")

   Étape 3 — Publication :
   POST https://graph.facebook.com/v25.0/{PAGE_ID}/video_reels
   params: {
     "upload_phase": "finish",
     "video_id": video_id,
     "access_token": TOKEN,
     "video_state": "PUBLISHED",
     "description": caption_text,
   }

2. Créer une fonction publish_as_reel(video_path, caption, page_id, token)
   dans src/service.py qui implémente les 3 étapes ci-dessus.

3. Dans la logique de publication Format A sur Facebook :
   - Si durée vidéo <= 90s → appeler publish_as_reel()
   - Si durée > 90s → garder l'ancien endpoint /videos (format long)

4. Ajouter dans config.json :
   {"facebook_use_reels_for_format_a": true}
   Ce flag permet de désactiver et revenir à l'ancien comportement si besoin.

5. Logger le résultat : "Publié comme Reel Facebook : {video_id}" ou erreur.

Tester avec force-publish Format A. Vérifier dans l'interface Facebook
que le post apparaît bien en tant que Reel (pas vidéo normale).
```

---

## TÂCHE 4 — ANGLE ENGINE + HOOK ENGINE (sans appel API supplémentaire)

### Objectif
Remplacer la génération "pilier → 3 points" par une sélection d'angle narratif
pondérée par les performances passées. Les hooks sont générés et scorés localement.

### Instructions pour OpenCode

```
CONTEXTE : [coller le contexte global ci-dessus]

TÂCHE 4 — ANGLE ENGINE + HOOK ENGINE

1. MIGRATION SQLite — Ajouter dans src/database.py les tables suivantes
   (dans la fonction d'initialisation de la DB, après les tables existantes) :

   CREATE TABLE IF NOT EXISTS viral_angles (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     pillar TEXT NOT NULL,
     angle_type TEXT NOT NULL,
     template TEXT NOT NULL,
     emotion TEXT NOT NULL,
     example TEXT,
     strength_score REAL DEFAULT 0.5,
     usage_count INTEGER DEFAULT 0,
     total_views INTEGER DEFAULT 0,
     total_likes INTEGER DEFAULT 0,
     total_comments INTEGER DEFAULT 0,
     last_used TEXT,
     created_at TEXT DEFAULT (datetime('now'))
   );

   CREATE TABLE IF NOT EXISTS post_genome (
     post_id INTEGER REFERENCES posts(id),
     pillar TEXT,
     angle_type TEXT,
     emotion TEXT,
     hook_type TEXT,
     first_frame_type TEXT,
     tts_enabled INTEGER,
     video_duration_seconds REAL,
     publish_hour INTEGER,
     platform TEXT,
     views_1h INTEGER DEFAULT 0,
     views_24h INTEGER DEFAULT 0,
     likes_24h INTEGER DEFAULT 0,
     shares_24h INTEGER DEFAULT 0,
     comments_24h INTEGER DEFAULT 0
   );


2. Crée le fichier src/angle_engine.py :

   import sqlite3, random
   from datetime import datetime, timedelta

   ANGLES_SEED = [
     # Format : (pillar, angle_type, template, emotion, example)
     # PROVISION ACTIVE
     ("Provision Active", "contre-intuitif",
      "La prière ne remplacera jamais {competence}.",
      "surprise", "la discipline financière"),
     ("Provision Active", "chiffre",
      "Si tu gagnes {montant} et dépenses {montant_moins}, ton problème n'est pas ton salaire.",
      "confrontation", "100 000 FCFA / 95 000 FCFA"),
     ("Provision Active", "histoire",
      "Il avait demandé à Dieu {chose}. Mais quand il l'a obtenu, il a fait cette erreur.",
      "curiosite", "un emploi"),
     ("Provision Active", "confrontation",
      "Être pauvre n'est pas un péché. Mais {glorifier_pauvrete} peut devenir un piège.",
      "colere", "glorifier sa pauvreté"),
     ("Provision Active", "revelation",
      "Personne ne t'enseigne {sujet} dans ton église. Et c'est peut-être pour ça que tu stagnes.",
      "curiosite", "la gestion de l'argent"),
     # SAGESSE
     ("Sagesse", "contre-intuitif",
      "La décision que tu retardes depuis {duree} te coûte plus cher que tu ne le crois.",
      "peur", "6 mois"),
     ("Sagesse", "chiffre",
      "{pourcentage}% des Africains qui réussissent ont fait ceci à {age} ans.",
      "surprise", "73% / 25"),
     ("Sagesse", "confrontation",
      "Tu lis les mêmes {livres} que tout le monde, mais ta vie ne change pas. Pourquoi ?",
      "confrontation", "livres chrétiens"),
     # DIGNITE
     ("Dignité", "transformation",
      "Il y a {duree}, il dormait dans {situation}. Voici ce qui a tout changé.",
      "espoir", "2 ans / une chambre partagée"),
     ("Dignité", "revelation",
      "Dieu ne t'a pas créé pour {limitation_sociale}. Voici la preuve dans ta Bible.",
      "foi", "rester au bas de l'échelle"),
     # LIBÉRATION
     ("Libération", "confrontation",
      "Tu appelles ça de la patience. Dieu appelle ça {vrai_nom}.",
      "colere", "de la peur"),
     ("Libération", "histoire",
      "Elle avait {situation_bloquante} pendant {duree}. Une phrase a tout changé.",
      "identification", "peur d'échouer / 7 ans"),
     # PRODUCTIVITE
     ("Productivité", "chiffre",
      "{heures} heures perdues par semaine sur {activite}. Multiplie par 52. C'est ta vraie richesse perdue.",
      "peur", "8h / les réseaux sociaux"),
     ("Productivité", "contre-intuitif",
      "Travailler plus n'est pas la solution. Voici ce que {personne_reussie} fait à la place.",
      "surprise", "les entrepreneurs africains qui réussissent"),
     # RESTAURATION RELATIONNELLE
     ("Restauration relationnelle", "identification",
      "Cette relation t'a blessé. Mais {verite_difficile} est aussi vraie.",
      "identification", "ta part dans le problème"),
     ("Restauration relationnelle", "revelation",
      "Dieu peut restaurer {relation_impossible}. Mais pas si tu fais encore {erreur}.",
      "espoir", "ce mariage / cette erreur"),
     # GÉNÉROSITÉ
     ("Générosité", "contre-intuitif",
      "Donner quand tu n'as presque rien est l'un des actes les plus intelligents financièrement. Voici pourquoi.",
      "surprise", None),
     ("Générosité", "chiffre",
      "Les {pourcentage}% les plus généreux de l'Église africaine sont aussi les {resultat}.",
      "surprise", "10% / plus prospères"),
   ]

   def init_angles(db_path: str):
       """Peuple viral_angles si vide."""
       conn = sqlite3.connect(db_path)
       c = conn.cursor()
       c.execute("SELECT COUNT(*) FROM viral_angles")
       if c.fetchone()[0] == 0:
           for row in ANGLES_SEED:
               c.execute(
                   "INSERT INTO viral_angles (pillar,angle_type,template,emotion,example) VALUES (?,?,?,?,?)",
                   row
               )
           conn.commit()
       conn.close()

   def pick_angle(db_path: str, pillar: str) -> dict:
       """
       Sélection pondérée : 70% meilleurs scores, 20% variations, 10% aléatoire.
       Évite les angles utilisés dans les 7 derniers jours.
       """
       conn = sqlite3.connect(db_path)
       c = conn.cursor()
       cutoff = (datetime.now() - timedelta(days=7)).isoformat()
       rows = c.execute(
           """SELECT id, angle_type, template, emotion, example, strength_score
              FROM viral_angles
              WHERE pillar=? AND (last_used IS NULL OR last_used < ?)
              ORDER BY strength_score DESC""",
           (pillar, cutoff)
       ).fetchall()
       conn.close()

       if not rows:
           # Fallback si tous récents
           conn = sqlite3.connect(db_path)
           c = conn.cursor()
           rows = c.execute(
               "SELECT id, angle_type, template, emotion, example, strength_score FROM viral_angles WHERE pillar=?",
               (pillar,)
           ).fetchall()
           conn.close()

       if not rows:
           return {"angle_type": "conseil", "template": "", "emotion": "espoir", "example": ""}

       r = random.random()
       if r < 0.70 and len(rows) >= 1:
           pool = rows[:max(1, len(rows)//2)]  # top 50%
       elif r < 0.90 and len(rows) >= 2:
           pool = rows[len(rows)//2:]           # bas 50% (exploration)
       else:
           pool = rows                           # tout (expérimentation)

       chosen = random.choice(pool)
       return {
           "id": chosen[0],
           "angle_type": chosen[1],
           "template": chosen[2],
           "emotion": chosen[3],
           "example": chosen[4],
           "strength_score": chosen[5]
       }

   def mark_angle_used(db_path: str, angle_id: int):
       conn = sqlite3.connect(db_path)
       conn.execute("UPDATE viral_angles SET last_used=?, usage_count=usage_count+1 WHERE id=?",
                    (datetime.now().isoformat(), angle_id))
       conn.commit()
       conn.close()

   def score_hooks_locally(hooks: list[str]) -> str:
       """
       Score 2-3 hooks sans appel API. Retourne le meilleur.
       Critères : présence d'un chiffre (+2), longueur 6-12 mots (+1),
       mot interrogatif (+1), verbe d'action (+1), mot négatif/tension (+1).
       """
       import re
       action_verbs = ["arrête","évite","fais","crée","construit","découvre","comprends","réalise"]
       tension_words = ["jamais","erreur","piège","bloque","peur","perds","échoue","stagne"]

       def score(h):
           s = 0
           words = h.split()
           if re.search(r'\d', h): s += 2
           if 6 <= len(words) <= 12: s += 1
           if any(w in h.lower() for w in ["pourquoi","comment","quand","si","quel"]): s += 1
           if any(v in h.lower() for v in action_verbs): s += 1
           if any(t in h.lower() for t in tension_words): s += 1
           return s

       return max(hooks, key=score)


3. Dans src/content.py, modifier le SYSTEM_PROMPT de génération Format A :

   a. Avant de construire le prompt, appeler :
      from src.angle_engine import pick_angle, mark_angle_used
      angle = pick_angle(DB_PATH, pillar)

   b. Injecter l'angle dans le prompt :
      ANGLE_INSTRUCTION = f"""
      ANGLE NARRATIF IMPOSÉ : {angle['angle_type']}
      TEMPLATE D'ANGLE : {angle['template']}
      ÉMOTION DOMINANTE : {angle['emotion']}
      EXEMPLE SI DISPONIBLE : {angle.get('example', '')}

      NE PAS utiliser la structure "X conseils / X points".
      Construire le contenu autour de l'angle ci-dessus.
      Générer 3 HOOKS candidats (champs hook_1, hook_2, hook_3).
      """

   c. Après génération, scorer les hooks localement :
      from src.angle_engine import score_hooks_locally
      best_hook = score_hooks_locally([
          content.get("hook_1",""), content.get("hook_2",""), content.get("hook_3","")
      ])
      content["hook"] = best_hook

   d. Marquer l'angle utilisé : mark_angle_used(DB_PATH, angle["id"])

4. Appeler init_angles(DB_PATH) dans le démarrage de l'app (app.py, après init_db).

Tester : lancer une génération Format A et vérifier dans les logs que l'angle
choisi est loggué ("Angle sélectionné : contre-intuitif (score 0.72)").
```

---

## TÂCHE 5 — MODE BATCH HEBDOMADAIRE

### Objectif
Générer 7 jours de contenu le dimanche en une session, stocker dans SQLite,
publier quotidiennement depuis la cache sans appel IA.

### Instructions pour OpenCode

```
CONTEXTE : [coller le contexte global ci-dessus]

TÂCHE 5 — MODE BATCH HEBDOMADAIRE

1. Ajouter dans SQLite (src/database.py) :

   CREATE TABLE IF NOT EXISTS content_queue (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     format TEXT NOT NULL,          -- 'A' ou 'B'
     pillar TEXT NOT NULL,
     scheduled_for TEXT NOT NULL,   -- ISO datetime de publication prévue
     content_json TEXT NOT NULL,    -- JSON du contenu généré
     media_path TEXT,               -- chemin vidéo/image déjà générée
     status TEXT DEFAULT 'pending', -- pending / published / failed
     platform TEXT NOT NULL,        -- 'facebook', 'youtube', 'both'
     created_at TEXT DEFAULT (datetime('now')),
     published_at TEXT
   );


2. Créer src/batch_generator.py :

   import json, sqlite3
   from datetime import datetime, timedelta
   from src.content import generate_content_a        # adapter selon ton import réel
   from src.content_declarations import generate_declaration  # adapter
   from src.angle_engine import pick_angle

   WEEKLY_PLAN = [
     # (jour_semaine 0=lundi, format, heure, pilier_override_ou_None)
     (0, "A", "08:15", None),  (0, "B", "12:30", None),
     (1, "A", "08:45", None),  (1, "B", "13:00", None),
     (2, "A", "09:00", None),  (2, "B", "12:15", None),
     (3, "A", "08:30", None),  (3, "B", "13:30", None),
     (4, "A", "08:00", None),  (4, "B", "12:00", None),
     (5, "A", "10:00", None),  (5, "B", "14:00", None),
     (6, "B", "11:00", None),  # dimanche : 1 seul post
   ]
   # Max 2 posts/jour respecté dans ce plan

   def generate_week_batch(db_path: str, start_date: datetime = None):
       """
       Génère et stocke 7 jours de contenu dans content_queue.
       start_date = prochain lundi si None.
       """
       if start_date is None:
           today = datetime.now().date()
           days_ahead = 7 - today.weekday() if today.weekday() != 0 else 0
           start_date = datetime.combine(today + timedelta(days=days_ahead), datetime.min.time())

       conn = sqlite3.connect(db_path)
       generated = 0

       for (weekday, fmt, heure, pilier) in WEEKLY_PLAN:
           pub_date = start_date + timedelta(days=weekday)
           h, m = map(int, heure.split(":"))
           scheduled_for = pub_date.replace(hour=h, minute=m, second=0).isoformat()

           # Éviter les doublons si batch déjà généré pour cette date
           existing = conn.execute(
               "SELECT id FROM content_queue WHERE scheduled_for=? AND status='pending'",
               (scheduled_for,)
           ).fetchone()
           if existing:
               continue

           try:
               if fmt == "A":
                   content = generate_content_a(pillar_override=pilier)
               else:
                   content = generate_declaration(pillar_override=pilier)

               conn.execute(
                   """INSERT INTO content_queue
                      (format, pillar, scheduled_for, content_json, status, platform)
                      VALUES (?,?,?,?,?,?)""",
                   (fmt, content.get("pillar",""), scheduled_for,
                    json.dumps(content, ensure_ascii=False), "pending", "both")
               )
               conn.commit()
               generated += 1
               print(f"[BATCH] Généré {fmt} pour {scheduled_for}")
           except Exception as e:
               print(f"[BATCH] Erreur {scheduled_for} : {e}")

       conn.close()
       return generated


3. Modifier APScheduler dans app.py pour :

   a. Ajouter un job hebdomadaire (dimanche 21h) :
      scheduler.add_job(generate_week_batch, 'cron', day_of_week='sun', hour=21, minute=0,
                        args=[DB_PATH], id='weekly_batch')

   b. Modifier les jobs de publication quotidiens pour LIRE depuis content_queue
      au lieu de générer en live :
      - Chercher dans content_queue les entrées avec status='pending' et
        scheduled_for entre maintenant et maintenant+30min
      - Si trouvé : publier, marquer status='published'
      - Si queue vide pour aujourd'hui : fallback sur génération en live

4. Ajouter dans Flask une route GET /batch-status retournant :
   {
     "queue_count": N,
     "next_scheduled": "2026-09-01T08:15:00",
     "week_generated": true/false
   }

5. Dans templates/index.html, ajouter un bouton "Générer la semaine prochaine"
   qui appelle POST /batch/generate-week. Afficher le nombre de posts en queue.

Tester : appeler POST /batch/generate-week et vérifier que content_queue
se remplit avec 13-14 entrées pour la semaine suivante.
```

---

## TÂCHE 6 — RECYCLAGE AUTOMATIQUE DES TOP PERFORMERS

### Objectif
Republier automatiquement les meilleurs contenus après 30 jours, avec variation
légère du hook. Zéro appel API Gemini. Zéro coût.

### Instructions pour OpenCode

```
CONTEXTE : [coller le contexte global ci-dessus]

TÂCHE 6 — RECYCLAGE AUTOMATIQUE

1. Dans src/database.py, ajouter à la table `posts` (si pas déjà présent) :
   ALTER TABLE posts ADD COLUMN recycled_from INTEGER REFERENCES posts(id);
   ALTER TABLE posts ADD COLUMN views_total INTEGER DEFAULT 0;
   ALTER TABLE posts ADD COLUMN likes_total INTEGER DEFAULT 0;
   (Utiliser "ALTER TABLE IF EXISTS" ou vérifier avec PRAGMA avant d'altérer)

2. Créer src/recycler.py :

   import sqlite3, json, random
   from datetime import datetime, timedelta

   HOOK_VARIATIONS = [
     "Tu l'as peut-être manqué la première fois : {}",
     "Une vérité qui change tout : {}",
     "Beaucoup ne l'ont jamais entendu : {}",
     "Rappel important pour toi aujourd'hui : {}",
     "Ce message revient parce qu'il en valait la peine : {}",
   ]

   def find_recyclable(db_path: str, min_views: int = 50, days_old: int = 30) -> list:
       """
       Trouve les posts avec bonnes performances publiés il y a >30 jours
       et non encore recyclés.
       """
       conn = sqlite3.connect(db_path)
       cutoff = (datetime.now() - timedelta(days=days_old)).isoformat()
       rows = conn.execute(
           """SELECT id, content_json, views_total, likes_total, format
              FROM posts
              WHERE published_at < ?
                AND views_total >= ?
                AND recycled_from IS NULL
                AND status = 'published'
              ORDER BY views_total DESC
              LIMIT 5""",
           (cutoff, min_views)
       ).fetchall()
       conn.close()
       return rows

   def recycle_post(db_path: str, original_id: int, content_json: str,
                    fmt: str, queue_table_path: str = None):
       """
       Prépare un post recyclé avec hook varié et l'insère dans content_queue.
       """
       content = json.loads(content_json)
       original_hook = content.get("hook", "")
       variation_template = random.choice(HOOK_VARIATIONS)
       content["hook"] = variation_template.format(original_hook)
       content["recycled"] = True

       scheduled_for = (datetime.now() + timedelta(days=random.randint(1, 3))).replace(
           hour=random.choice([8, 13, 18]),
           minute=random.randint(0, 30),
           second=0
       ).isoformat()

       conn = sqlite3.connect(db_path)
       conn.execute(
           """INSERT INTO content_queue
              (format, pillar, scheduled_for, content_json, status, platform)
              VALUES (?,?,?,?,?,?)""",
           (fmt, content.get("pillar",""), scheduled_for,
            json.dumps(content, ensure_ascii=False), "pending", "facebook")
           # Recycler sur Facebook seulement (plateforme à plus grand potentiel viral)
       )
       conn.commit()
       conn.close()
       return scheduled_for

   def run_recycling(db_path: str):
       """Point d'entrée : trouve et planifie les recyclages."""
       candidates = find_recyclable(db_path, min_views=30)
       count = 0
       for (pid, cjson, views, likes, fmt) in candidates[:2]:  # max 2 recyclages/cycle
           scheduled = recycle_post(db_path, pid, cjson, fmt)
           print(f"[RECYCLER] Post {pid} ({views} vues) planifié pour {scheduled}")
           count += 1
       return count


3. Dans app.py (APScheduler), ajouter un job mensuel :
   scheduler.add_job(run_recycling, 'interval', days=14, args=[DB_PATH],
                     id='recycler')

4. Dans Flask, ajouter route POST /recycler/run (pour test manuel)
   et GET /recycler/candidates (retourne la liste des candidats avec leurs stats).

5. Dans templates/index.html, ajouter une section "Recyclage" affichant
   les candidats disponibles et un bouton "Planifier maintenant".

Tester : insérer manuellement dans posts un post avec views_total=60
et published_at = il y a 31 jours, puis appeler POST /recycler/run.
Vérifier dans content_queue que le post recyclé apparaît.
```

---

## TÂCHE 7 — LEARNING LOOP SQL (hebdomadaire, sans ML)

### Objectif
Chaque semaine, mettre à jour les strength_scores des angles en fonction
des vraies performances. Aucune bibliothèque ML. Juste du SQL.

### Instructions pour OpenCode

```
CONTEXTE : [coller le contexte global ci-dessus]

TÂCHE 7 — LEARNING LOOP SQL

Prérequis : TÂCHE 4 implémentée (tables viral_angles + post_genome).

1. Créer src/learning.py :

   import sqlite3
   from datetime import datetime, timedelta

   def fetch_analytics_from_platforms(db_path: str):
       """
       Récupère les stats réelles depuis l'API Facebook (Graph API)
       pour les posts des 14 derniers jours.
       Met à jour post_genome avec views_24h, likes_24h, etc.
       """
       # Charger les tokens depuis Windows Credential Manager (keyring)
       import keyring
       token = keyring.get_password("voix_prosperite", "fb_access_token")
       page_id = keyring.get_password("voix_prosperite", "fb_page_id")

       import requests, json
       conn = sqlite3.connect(db_path)

       # Récupérer les post_ids Facebook des 14 derniers jours
       cutoff = (datetime.now() - timedelta(days=14)).isoformat()
       posts = conn.execute(
           "SELECT id, fb_post_id FROM posts WHERE published_at > ? AND fb_post_id IS NOT NULL",
           (cutoff,)
       ).fetchall()

       for (post_id, fb_post_id) in posts:
           try:
               r = requests.get(
                   f"https://graph.facebook.com/v25.0/{fb_post_id}",
                   params={
                       "fields": "insights.metric(post_impressions,post_reactions_by_type_total,post_shares)",
                       "access_token": token
                   }, timeout=10
               )
               data = r.json()
               insights = data.get("insights", {}).get("data", [])

               views = 0; likes = 0; shares = 0
               for metric in insights:
                   if metric["name"] == "post_impressions":
                       views = metric["values"][-1]["value"] if metric.get("values") else 0
                   if metric["name"] == "post_reactions_by_type_total":
                       v = metric["values"][-1]["value"] if metric.get("values") else {}
                       likes = sum(v.values()) if isinstance(v, dict) else 0
                   if metric["name"] == "post_shares":
                       shares = metric["values"][-1]["value"] if metric.get("values") else 0

               conn.execute(
                   """UPDATE post_genome SET views_24h=?, likes_24h=?, shares_24h=?
                      WHERE post_id=?""",
                   (views, likes, shares, post_id)
               )
               conn.execute(
                   "UPDATE posts SET views_total=?, likes_total=? WHERE id=?",
                   (views, likes, post_id)
               )
           except Exception as e:
               print(f"[LEARNING] Erreur analytics post {post_id}: {e}")
       conn.commit()
       conn.close()


   def update_angle_scores(db_path: str):
       """
       Met à jour strength_score de chaque angle selon les performances moyennes
       des posts qui l'ont utilisé.
       Score = 0.5*norm_views + 0.3*norm_likes + 0.2*norm_shares
       Normalisé entre 0 et 1 par rapport au maximum observé.
       """
       conn = sqlite3.connect(db_path)

       # Calculer les stats agrégées par angle
       conn.execute("""
           UPDATE viral_angles
           SET strength_score = (
               SELECT COALESCE(
                 (0.5 * AVG(CAST(pg.views_24h AS REAL)) / NULLIF(
                   (SELECT MAX(views_24h) FROM post_genome WHERE views_24h > 0), 0)
                 + 0.3 * AVG(CAST(pg.likes_24h AS REAL)) / NULLIF(
                   (SELECT MAX(likes_24h) FROM post_genome WHERE likes_24h > 0), 0)
                 + 0.2 * AVG(CAST(pg.shares_24h AS REAL)) / NULLIF(
                   (SELECT MAX(shares_24h) FROM post_genome WHERE shares_24h > 0), 0)),
               0.3)  -- score par défaut si pas encore de données
               FROM post_genome pg
               JOIN posts p ON p.id = pg.post_id
               WHERE pg.angle_type = viral_angles.angle_type
                 AND pg.pillar = viral_angles.pillar
                 AND pg.views_24h IS NOT NULL
           )
           WHERE id IN (
               SELECT DISTINCT va.id FROM viral_angles va
               JOIN post_genome pg ON pg.angle_type = va.angle_type
           )
       """)
       conn.commit()

       # Log les top angles
       tops = conn.execute(
           "SELECT pillar, angle_type, strength_score FROM viral_angles ORDER BY strength_score DESC LIMIT 5"
       ).fetchall()
       for row in tops:
           print(f"[LEARNING] Top angle : {row[0]} | {row[1]} | score={row[2]:.3f}")
       conn.close()


   def run_learning_cycle(db_path: str):
       """Point d'entrée hebdomadaire."""
       print("[LEARNING] Début du cycle d'apprentissage...")
       fetch_analytics_from_platforms(db_path)
       update_angle_scores(db_path)
       print("[LEARNING] Cycle terminé.")


2. Dans app.py (APScheduler), ajouter :
   scheduler.add_job(run_learning_cycle, 'cron', day_of_week='mon', hour=6,
                     args=[DB_PATH], id='learning_cycle')
   (Chaque lundi matin, avant les publications)

3. Dans app.py, ajouter route POST /learning/run (pour déclencher manuellement).

Tester : appeler POST /learning/run et vérifier dans viral_angles
que les strength_scores sont mis à jour (pas tous à 0.5).
```

---

## TÂCHE 8 — VIRAL DASHBOARD (Flask, léger, sans JS framework)

### Objectif
Une page /dashboard dans l'interface Flask existante montrant les statistiques
clés, les meilleurs angles, et les recommandations auto-générées.
Zéro bibliothèque JS externe. HTML pur + CSS inline. Ultra-léger.

### Instructions pour OpenCode

```
CONTEXTE : [coller le contexte global ci-dessus]

TÂCHE 8 — VIRAL DASHBOARD

1. Ajouter une route Flask GET /dashboard dans app.py :

   @app.route('/dashboard')
   def dashboard():
       conn = sqlite3.connect(DB_PATH)

       # Stats générales
       total_posts = conn.execute("SELECT COUNT(*) FROM posts WHERE status='published'").fetchone()[0]
       avg_views = conn.execute("SELECT AVG(views_total) FROM posts WHERE views_total > 0").fetchone()[0] or 0
       avg_likes = conn.execute("SELECT AVG(likes_total) FROM posts WHERE likes_total > 0").fetchone()[0] or 0

       # Top 5 angles
       top_angles = conn.execute(
           """SELECT pillar, angle_type, strength_score, usage_count
              FROM viral_angles ORDER BY strength_score DESC LIMIT 5"""
       ).fetchall()

       # Top 3 posts
       top_posts = conn.execute(
           """SELECT pillar, hook_type, views_24h, likes_24h, shares_24h, platform
              FROM post_genome pg JOIN posts p ON p.id=pg.post_id
              WHERE pg.views_24h > 0 ORDER BY pg.views_24h DESC LIMIT 3"""
       ).fetchall()

       # Queue status
       queue_count = conn.execute(
           "SELECT COUNT(*) FROM content_queue WHERE status='pending'"
       ).fetchone()[0]

       # Recommandations auto
       best_hour = conn.execute(
           """SELECT publish_hour, AVG(views_24h) as avg_v FROM post_genome
              WHERE views_24h > 0 GROUP BY publish_hour ORDER BY avg_v DESC LIMIT 1"""
       ).fetchone()
       best_emotion = conn.execute(
           """SELECT emotion, AVG(pg.views_24h) FROM post_genome pg
              JOIN viral_angles va ON va.angle_type=pg.angle_type
              WHERE pg.views_24h > 0 GROUP BY va.emotion ORDER BY 2 DESC LIMIT 1"""
       ).fetchone()

       conn.close()
       return render_template('dashboard.html',
           total_posts=total_posts, avg_views=round(avg_views),
           avg_likes=round(avg_likes), top_angles=top_angles,
           top_posts=top_posts, queue_count=queue_count,
           best_hour=best_hour, best_emotion=best_emotion)


2. Créer templates/dashboard.html :
   Template HTML minimaliste avec style inline (pas de CSS externe, pas de JS framework).
   Utiliser uniquement des balises HTML basiques + style="..." inline.
   Structure de la page :

   <h1>🔥 Viral Dashboard — Voix de Prospérité</h1>

   Section 1 — Chiffres clés (3 boxes côte à côte) :
   - Posts publiés : {{total_posts}}
   - Vues moyennes : {{avg_views}}
   - Likes moyens : {{avg_likes}}

   Section 2 — Top 5 Angles :
   Table HTML : Pilier | Angle | Score | Utilisations
   Colorer la ligne en vert si score > 0.6, orange si 0.3-0.6, rouge si < 0.3

   Section 3 — Top 3 Posts :
   Table : Pilier | Émotion | Vues | Likes | Partages | Plateforme

   Section 4 — Queue :
   "{{queue_count}} posts en attente de publication"
   Bouton "Générer la semaine" → POST /batch/generate-week

   Section 5 — Recommandations auto :
   "✅ Meilleur horaire : {{best_hour[0]}}h"
   "✅ Émotion qui performe : {{best_emotion[0] if best_emotion else 'données insuffisantes'}}"
   "⚠️ Réduire : titres '3 conseils', images abstraites"

   Ajouter un lien vers /dashboard dans la navigation de templates/index.html.

3. Style cible : sobre, lisible sur petit écran, couleurs noires/blanches/vert.
   Pas de Bootstrap, pas de Tailwind, pas de jQuery.
   La page doit se charger en < 200ms sur l'i5-2520M.

Tester : ouvrir http://localhost:5000/dashboard et vérifier que la page
s'affiche sans erreur même si les tables sont vides (valeurs par défaut = 0).
```

---

## ORDRE D'IMPLÉMENTATION RECOMMANDÉ

| Priorité | Tâche | Impact | Effort | Urgence |
|----------|-------|--------|--------|---------|
| 1 | Anti-shadowban | 🔴 Critique | Faible | Aujourd'hui |
| 2 | Endpoint Reels | 🔴 Critique | Faible | Cette semaine |
| 3 | Edge-TTS voix | 🟠 Élevé | Moyen | Cette semaine |
| 4 | Angle + Hook Engine | 🟠 Élevé | Moyen | Semaine 2 |
| 5 | Mode Batch | 🟡 Moyen | Moyen | Semaine 2 |
| 6 | Recyclage | 🟡 Moyen | Faible | Semaine 3 |
| 7 | Learning Loop | 🟡 Moyen | Moyen | Après 30 posts |
| 8 | Dashboard | 🟢 Faible | Faible | Quand 6 & 7 faits |

## CONTRAINTES RAPPELÉES POUR CHAQUE SESSION OPENCODE

- FFmpeg : JAMAIS de `-c:v h264_qsv` ni NVENC. Uniquement `-c:v libx264 -preset veryfast -crf 28 -threads 4`
- Pas de torch, sklearn, pandas, numpy (trop lourds pour i5-2520M)
- SQLite uniquement, pas de PostgreSQL ni Redis
- Windows compatible (pas de fork(), utiliser threading ou APScheduler)
- Tout test doit être manuel et vérifiable dans les logs ou via une route Flask
- Chaque tâche est indépendante : ne pas casser les fonctionnalités existantes
