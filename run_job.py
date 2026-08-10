from __future__ import annotations

import argparse
import sys
from datetime import datetime

from src.scheduler_log import log_run


def _matching_formats(database, slot: str | None, forced_output: str | None) -> list[dict]:
    """Renvoie les formats actifs de la BD correspondant au créneau (ou au type forcé).

    Retourne [] si aucun format actif ne matche ; dans ce cas l'appelant
    retombe sur l'ancien mappage config['schedule'] pour ne rien casser.
    """
    formats = database.list_formats(only_active=True)
    if not formats:
        return []
    if forced_output:
        output_types = {"video": "short_comment", "declaration": "image_text"}
        return [fmt for fmt in formats if fmt["output_type"] == output_types[forced_output]]
    if slot is None:
        return formats
    return [fmt for fmt in formats if slot in fmt["schedule"]]


@log_run("run_job")
def _run() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # Imports déplacés ici volontairement : si config.py, service.py ou une
    # dépendance échoue à l'import (ex. module manquant, config.json invalide),
    # l'exception est désormais capturée et journalisée par @log_run au lieu de
    # faire planter la tâche planifiée sans laisser de trace.
    from src.config import format_for, load_config
    from src.logging_setup import setup_logging
    from src.service import PublicationService

    parser = argparse.ArgumentParser(description="Publication automatique Voix de Prospérité en Christ")
    parser.add_argument("--dry-run", action="store_true", help="Prépare et archive sans publier")
    parser.add_argument("--catch-up", action="store_true", help="Publie les créneaux manqués du jour")
    parser.add_argument("--manual", action="store_true",
                        help="Publie les fichiers importés (assets/pending) aux créneaux manuels dus")
    parser.add_argument("--format", choices=("video", "declaration"), default=None,
                        help="Force un format (défaut : ceux des formats actifs du créneau)")
    args = parser.parse_args()
    config = load_config()
    service = PublicationService(config, setup_logging(config))
    database = service.database
    # Migration : crée les deux formats par défaut si la table post_formats est vide.
    database.seed_default_formats(config["schedule"])

    if args.manual:
        from src.manual_scheduler import run_manual

        result = run_manual(config, service, setup_logging(config), dry_run=args.dry_run)
        print(result)
        return

    def run_one(fmt: dict | None, slot: str | None, scheduled_for: str) -> dict:
        if fmt is None:
            output_type = args.format or format_for(config, slot)
            return service.publish(
                scheduled_for=scheduled_for,
                dry_run=args.dry_run,
                format=output_type,
            )
        return service.publish(
            scheduled_for=scheduled_for,
            dry_run=args.dry_run,
            format=service.normalize_format(fmt["output_type"]),
            prompt=fmt["prompt"] or None,
            networks=fmt["networks"],
            format_name=fmt["name"],
        )

    if args.catch_up:
        # Filet de sécurité : purge les médias de plus de 2 jours au cas où le
        # nettoyage normal aurait été sauté (crash, échec partiel, ...).
        from src.cleanup import purge_old_media
        from src.config import absolute_path

        logger = setup_logging(config)
        for folder in ("images", "videos"):
            purge_old_media(absolute_path(config["paths"][folder]), keep_days=2, logger=logger)
        now = datetime.now()
        due = [slot for slot in config["schedule"] if slot <= now.strftime("%H:%M") and service.database.needs_catch_up(slot)]
        if not due:
            print("Aucune publication en retard.")
            return
        for slot in due:
            for fmt in _matching_formats(database, slot, args.format) or [None]:
                label = fmt["name"] if fmt else (args.format or format_for(config, slot))
                print(f"[{slot}] {label}: " + str(
                    run_one(fmt, slot, f"{now.date().isoformat()}T{slot}")
                ))
    else:
        now = datetime.now()
        current = now.strftime("%H:%M")
        # Collage sur le dernier créneau planifié ≤ maintenant : identique au
        # comportement historique quand on lance manuellement entre deux créneaux.
        slot = max(
            (s for s in config["schedule"] if s <= current),
            default=current,
        )
        targets = _matching_formats(database, slot, args.format) or [None]
        if not targets:
            print("Aucun format actif pour ce créneau, rien à publier.")
            return
        for fmt in targets:
            label = fmt["name"] if fmt else (args.format or format_for(config, slot))
            print(f"[{slot}] {label}: " + str(
                run_one(fmt, slot, now.isoformat(timespec="minutes"))
            ))


def main() -> None:
    try:
        _run()
    except BaseException:
        # Déjà journalisé en détail par @log_run ci-dessus. On force un code de
        # sortie non nul pour que le Planificateur de tâches Windows déclenche
        # RestartCount (défini dans register_tasks.ps1) au lieu de considérer
        # la tâche comme terminée avec succès.
        sys.exit(1)


if __name__ == "__main__":
    main()
