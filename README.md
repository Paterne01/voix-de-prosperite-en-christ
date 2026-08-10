# Voix de Prospérité en Christ

Application Windows locale qui prépare et publie deux publications Facebook par jour, avec une image de marque, une légende courte et le contenu détaillé dans le premier commentaire.

## Installation

1. Installez Python **3.12 ou plus récent** depuis python.org, en cochant « Add Python to PATH ».
2. Double-cliquez sur `install.bat`.
3. Placez le logo officiel dans `assets/logo.png` (PNG transparent conseillé).
4. Lancez `start.bat`, puis ouvrez `http://127.0.0.1:8765`.
5. Dans l’interface, indiquez le Page ID, le chemin du logo, les horaires et les clés. Les clés sont enregistrées dans le Gestionnaire d’identifiants Windows, pas dans `config.json`.
6. Préparez un test. Vérifiez l’image, le texte et les archives avant toute publication forcée.
7. Ouvrez PowerShell dans le dossier puis exécutez :

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\register_tasks.ps1
```

Gardez le PC allumé. Les tâches manquées sont déclenchées dès que Windows devient disponible.

## Meta Graph API

Créez une application Meta et obtenez un jeton de page avec, au minimum, `pages_show_list`, `pages_read_engagement`, `pages_manage_posts` et les permissions Meta nécessaires à la gestion des commentaires. Utilisez un jeton **de page**, jamais votre jeton personnel. Entrez le Page ID et le jeton dans l’interface, puis exécutez d’abord un test sur une page de test.

L’application envoie l’image sur `/{page-id}/photos`, récupère l’identifiant de publication, puis crée le premier commentaire sur `/{post-id}/comments`. Les erreurs Meta, y compris un jeton expiré ou des permissions insuffisantes, sont archivées dans `Logs/logs.txt` sans afficher le jeton.

## Images

- **Visuel local premium** (défaut) : composition bleu marine/or, titre, logo et mention « Détails en commentaire ». Il fonctionne sans quota.
- **Cloud expérimental** : implémentation Hugging Face. Enregistrez un jeton Hugging Face, activez l’option dans l’interface et sélectionnez ce mode. Les crédits gratuits ne constituent pas une garantie de service.
- **Validation manuelle** : le contenu et l’archive sont produits, mais rien n’est envoyé à Facebook tant qu’une image n’est pas fournie et le test relancé dans un mode publiable.

## Archives, sauvegarde et restauration

- `Images/` : images créées.
- `Textes/` : légendes et commentaires.
- `Logs/logs.txt` : événements et erreurs.
- `BaseDeDonnées/voix_prosperite.sqlite3` : historique et prévention des doublons.

Pour sauvegarder, arrêtez l’application puis copiez ces quatre dossiers dans un emplacement sûr. Pour restaurer, remettez-les à la même place. Les clés restent dans le coffre Windows du compte qui les a enregistrées : réenregistrez-les après un changement de PC.

## Maintenance et dépannage

- Lancez `python run_job.py --dry-run` pour vérifier une génération sans publier.
- Lancez `python run_job.py --catch-up` pour contrôler le rattrapage du jour.
- Si l’interface ne s’ouvre pas, relancez `start.bat` et consultez `Logs/logs.txt`.
- Si Meta refuse la publication, vérifiez le Page ID, la validité du jeton et les permissions de l’application.
- Les horaires sont modifiables dans l’interface. Relancez `scripts/register_tasks.ps1` après toute modification afin d’actualiser les tâches Windows.

## Évolution vers d’autres réseaux

La génération, la base historique et les images sont indépendantes du canal. Ajoutez un adaptateur de publication par réseau (Instagram, LinkedIn, etc.) sans changer le moteur éditorial, puis ajoutez les champs d’identifiants et statuts correspondants à SQLite.

## TikTok (Content Posting API — Direct Post)

L’application peut publier les **vidéos** (format vidéo uniquement) sur TikTok via la Content Posting API.

1. Créez une app TikTok Developers, ajoutez Login Kit + Content Posting API (scopes `video.publish`, `user.info.basic`) et enregistrez la redirection `http://127.0.0.1:*/callback/`.
2. Dans l’interface, saisissez **TikTok Client Key** et **TikTok Client Secret** (coffre Windows), puis cliquez sur **Connecter TikTok** pour autoriser le compte.
3. Cochez **TikTok** dans la configuration et enregistrez.
4. Lancez un test : `python run_job.py --dry-run --format video`, puis une publication forcée depuis l’interface.

Notes importantes :

- Tant que l’app n’est **pas auditée** par TikTok, seuls des posts **privés** sont acceptés (`SELF_ONLY` par défaut dans `config.json` → `tiktok.privacy_level`). Après audit, passez à `PUBLIC_TO_EVERYONE`.
- Les vidéos sont des créations IA : le flag `is_aigc` (`true` par défaut) les étiquette automatiquement « AI-generated », conformément aux règles TikTok.
- Le flux technique est : `video/init` → upload du fichier en chunks (PUT `Content-Range`) → attente du statut `status/fetch` (`PUBLISH_COMPLETE` ou `FAILED`). Les jetons se rafraîchissent automatiquement.
- Déconnexion/réautorisation : re-cliquez sur **Connecter TikTok** en cas de jeton refusé.
