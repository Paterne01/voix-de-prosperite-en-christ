from __future__ import annotations

import functools
import time
import traceback
from datetime import datetime
from pathlib import Path

# Chemin calculé à partir de l'emplacement du fichier lui-même (racine du projet /
# Logs/scheduler.log), donc valable même si config.json est absent, corrompu, ou si
# le WorkingDirectory n'est pas celui attendu.
_LOG_PATH = Path(__file__).resolve().parent.parent / "Logs" / "scheduler.log"


def _write(line: str) -> None:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def log_run(command: str):
    """Décorateur : journalise chaque exécution d'une tâche planifiée dans
    Logs/scheduler.log (heure, commande, durée, succès/échec, traceback complet).

    Volontairement indépendant de src.config / src.logging_setup : si le
    chargement de la configuration applicative échoue, on veut quand même une
    trace exploitable plutôt qu'une fenêtre qui se ferme silencieusement.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.monotonic()
            started_at = datetime.now().isoformat(timespec="seconds")
            try:
                result = func(*args, **kwargs)
                duration = time.monotonic() - start
                _write(f"{started_at} | {command} | duree={duration:.1f}s | SUCCES")
                return result
            except SystemExit:
                raise
            except BaseException:
                duration = time.monotonic() - start
                _write(f"{started_at} | {command} | duree={duration:.1f}s | ECHEC")
                _write(traceback.format_exc())
                raise

        return wrapper

    return decorator
