# AGENTS.md — Voix de Prospérité en Christ

Règles de collaboration pour les agents d'édition (opencode et autres)
travaillant sur ce dépôt.

## Synchronisation GitHub automatique

- Dépôt distant : `https://github.com/Paterne01/voix-de-prosperite-en-christ.git`
  (branche `main`). La branche locale est `master` ; elle est poussée vers `main`.
- Une tâche planifiée Windows `VoixDeProsperite_SyncGitHub` exécute
  `scripts/sync-github.ps1` toutes les 5 minutes : elle indexe, commite
  (`sync: mise à jour automatique (date)`) et pousse tout changement.
- Chaque agent DOIT en plus pousser immédiatement après chaque commit de
  session : `git push origin master:main`.
- Garde-fou : `scripts/sync-github.ps1` refuse de pousser un motif de secret
  (jetons, clés API, mots de passe). En cas de blocage, les détails figurent
  dans `Logs/push-error.log`.

## Confidentialité — à respecter absolument

- Ne jamais écrire ni commiter : `config.json` (réel), `.env`, tokens
  `*.pickle`, `BaseDeDonnées/`, `Images/`, `Videos/`, `Vidéos/`, `Textes/`,
  `Logs/`, `assets/pending/`, `assets/format_a/`, `assets/format_b/`,
  `assets/logo.png`, `*.sqlite3`, `*.log` (tous déjà dans `.gitignore`).
- Utiliser les credentials natifs / le trousseau (keyring) ; jamais de secrets
  en dur dans le code.
- Pour toute nouvelle dépendance de secret, fournir un modèle `.example` et
  jamais le fichier réel.

## Vérification avant de conclure une tâche

- `pytest tests` doit passer (suite dans `tests/test_core.py`).
- Le serveur Flask doit répondre : `GET /`, `GET /api/formats`,
  `GET /api/scheduler`.
- Valider l'état avec `git status` puis pousser avec
  `git push origin master:main`.
