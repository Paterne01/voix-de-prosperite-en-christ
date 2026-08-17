"""Logique de publication partagée entre la CLI (run_job.py) et le planificateur
intégré (src/scheduler.py). Évite la duplication du code de publication."""

from __future__ import annotations

from datetime import datetime

from src.scheduler_log import log_run


def matching_formats(database, slot: str | None, forced_output: str | None) -> list[dict]:
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


def run_slot(config: dict, service, fmt: dict | None, slot: str | None, scheduled_for: str, dry_run: bool = False) -> dict:
    """Prépare et publie (ou dry-run) un créneau pour un format donné."""
    from src.config import format_for

    if fmt is None:
        output_type = format_for(config, slot)
        return service.publish(
            scheduled_for=scheduled_for,
            dry_run=dry_run,
            format=output_type,
        )
    return service.publish(
        scheduled_for=scheduled_for,
        dry_run=dry_run,
        format=service.normalize_format(fmt["output_type"]),
        prompt=fmt["prompt"] or None,
        networks=fmt["networks"],
        format_name=fmt["name"],
        tier=fmt.get("tier", "free"),
    )


@log_run("run_manual")
def run_manual_tick(config: dict, service, logger, dry_run: bool = False) -> dict:
    from src.manual_scheduler import run_manual

    return run_manual(config, service, logger, dry_run=dry_run)


@log_run("run_catch_up")
def run_catch_up(config: dict, service, dry_run: bool = False, forced_output: str | None = None) -> dict:
    """Publie les créneaux manqués du jour. Retourne un résumé."""
    from src.cleanup import purge_old_media
    from src.config import absolute_path

    logger = service.logger
    for folder in ("images", "videos"):
        purge_old_media(absolute_path(config["paths"][folder]), keep_days=2, logger=logger)
    now = datetime.now()
    due = []
    for slot in config["schedule"]:
        if slot <= now.strftime("%H:%M") and service.database.needs_catch_up(slot):
            due.append(slot)
    if not due:
        summary = {"status": "idle", "published": 0, "creneaux": []}
        print("Aucune publication en retard.")
        return summary
    results = []
    for slot in due:
        for fmt in matching_formats(service.database, slot, forced_output) or [None]:
            label = fmt["name"] if fmt else None
            result = run_slot(config, service, fmt, slot, f"{now.date().isoformat()}T{slot}", dry_run=dry_run)
            results.append({"creneau": slot, "format": label, "result": result})
            print(f"[{slot}] {label or 'defaut'}: " + str(result))
    published = sum(1 for r in results if r["result"].get("status") in ("published", "partial"))
    blocked = sum(1 for r in results if r["result"].get("status") == "failed")
    return {"status": "done", "published": published, "bloqués": blocked, "creneaux": results}