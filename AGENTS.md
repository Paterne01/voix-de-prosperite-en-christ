# AGENTS.md — Voix de Prospérité en Christ

Règles de collaboration pour les agents d'édition (opencode et autres)
travaillant sur ce dépôt.

## Synchronisation GitHub automatique

- Dépôt distant : `https://github.com/Paterne01/voix-de-prosperite-en-christ.git`
  (branche `main`). La branche locale est `master` ; elle est poussée vers `main`.
- Une tâche planifiée Windows `VoixDeProsperite_SyncGitHub` exécute
  `scripts/sync-github.ps1` toutes les 5 minutes : elle indexe, commite
  (`sync: mise à jour automatique (date)`) et pousse tout changement.
  Elle tourne **en arrière-plan, sans fenêtre** : action `wscript.exe` → un
  launcher `.vbs` dédié généré dans `scripts/launchers/` (jamais de
  `powershell.exe` nu en action de tâche).
- Chaque agent DOIT en plus pousser immédiatement après chaque commit de
  session : `git push origin master:main`.
- Garde-fou : `scripts/sync-github.ps1` refuse de pousser un motif de secret
  (jetons, clés API, mots de passe). En cas de blocage, les détails figurent
  dans `Logs/push-error.log`.

## Exécution en arrière-plan — règle PC (tous projets/tâches planifiées)

Les fenêtres de terminal qui s'ouvrent pour exécuter des tâches planifiées
doivent rester invisibles en permanence.

- Toute tâche planifiée Windows créée sur ce PC doit être silencieuse : action
  `wscript.exe` (processus sans console) exécutant un launcher `.vbs` dédié
  (généré par l'assistant ci-dessous ; commande en dur dans le VBS, aucune
  imbrication de guillemets).
- Pour créer une tâche silencieuse : `powershell -File scripts\register-background-task.ps1
  -TaskName "<Nom>" -ScriptPath "<chemin absolu>" -RepeatMinutes N`.
- Lancement ponctuel masqué : `wscript scripts\run-hidden.vbs "commande"`.
- Ne jamais utiliser un `powershell.exe` ou `.bat` nu comme action de tâche
  (fenêtre qui clignote).
- Note : le logon non-interactif S4U supprime la fenêtre mais exige des droits
  admin ; la méthode `wscript.exe` + VBS est équivalente et sans admin.

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
