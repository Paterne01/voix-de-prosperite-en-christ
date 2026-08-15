from __future__ import annotations

import argparse
import sys
from datetime import datetime

from src.console import configure_console
from src.jobs import matching_formats, run_slot
from src.scheduler_log import log_run


@log_run("run_job")
def _run() -> None:
    configure_console()
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
    parser.add_argument("--check-ai", action="store_true",
                        help="Teste chaque fournisseur d'IA configuré et affiche celui qui répond")
    args = parser.parse_args()
    config = load_config()

    if args.check_ai:
        from src.llm import check_provider, ordered_providers

        print(f"Provider principal configuré : {config.get('ai', {}).get('provider', 'gemini')}")
        for provider in ordered_providers(config):
            ok, message = check_provider(config, provider.name)
            print(("OK  " if ok else "FAIL") + f"  {message}")
        return

    service = PublicationService(config, setup_logging(config))
    database = service.database
    # Migration : crée les deux formats par défaut si la table post_formats est vide.
    database.seed_default_formats(config["schedule"])

    if args.manual:
        from src.jobs import run_manual_tick

        result = run_manual_tick(config, service, setup_logging(config), dry_run=args.dry_run)
        print(result)
        return

    if args.catch_up:
        from src.jobs import run_catch_up

        result = run_catch_up(config, service, dry_run=args.dry_run, forced_output=args.format)
        print(result)
        return
    now = datetime.now()
    current = now.strftime("%H:%M")
    # Collage sur le dernier créneau planifié ≤ maintenant : identique au
    # comportement historique quand on lance manuellement entre deux créneaux.
    slot = max(
        (s for s in config["schedule"] if s <= current),
        default=current,
    )
    targets = matching_formats(database, slot, args.format) or [None]
    if not targets:
        print("Aucun format actif pour ce créneau, rien à publier.")
        return
    for fmt in targets:
        label = fmt["name"] if fmt else (args.format or format_for(config, slot))
        # Garde-fou anti-doublon : un contenu existe déjà pour ce créneau (le
        # serveur APScheduler ou une autre instance l'a peut-être publié).
        if not args.dry_run and not database.needs_catch_up(slot):
            print(f"[{slot}] {label}: déjà publié, skip (anti-doublon).")
            continue
        print(f"[{slot}] {label}: " + str(
            run_slot(config, service, fmt, slot, f"{now.date().isoformat()}T{slot}", dry_run=args.dry_run)
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
