from __future__ import annotations

import time
from pathlib import Path


def purge_published_media(paths: list[Path], logger=None) -> None:
    """À appeler UNIQUEMENT après confirmation de succès de la publication sur
    tous les réseaux activés pour ce post (Facebook, YouTube, ...). Le réseau
    est déjà l'archive de référence : garder l'image/vidéo en local n'apporte
    rien et alourdit un PC aux ressources limitées.

    Ne jamais appeler ceci avant confirmation : si la publication échoue et
    qu'un nouvel essai est nécessaire, les fichiers doivent encore exister.
    """
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            if logger:
                logger.warning("Impossible de supprimer %s : %s", path, exc)


def purge_old_media(directory: Path, keep_days: int = 2, logger=None) -> int:
    """Nettoyage de sécurité à lancer périodiquement (ex. depuis la tâche de
    rattrapage au démarrage) : supprime tout fichier de `directory` plus vieux
    que keep_days, au cas où purge_published_media n'aurait pas tourné (crash,
    échec partiel, etc.). Renvoie le nombre de fichiers supprimés.
    """
    if not directory.exists():
        return 0
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for path in directory.iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError as exc:
                if logger:
                    logger.warning("Nettoyage : impossible de supprimer %s : %s", path, exc)
    return removed
