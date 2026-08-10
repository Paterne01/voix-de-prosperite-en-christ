from __future__ import annotations

import time
from datetime import datetime


def manual_slots(config: dict) -> list[str]:
    """Créneaux de publication du Format C (fichiers importés).

    mode "slots" → liste fixe d'horaires (ex. ["04:00", "20:00"]).
    mode "interval" → série commençant à start_hour, tous les interval_hours
    (1h, 2h, 3h, 4h, 6h, 12h, 24h = 1j). Retourne des horaires HH:MM triés.
    """
    schedule = config.get("manual_schedule") or {}
    if schedule.get("mode") == "interval":
        interval = max(1, int(schedule.get("interval_hours") or 4))
        start = schedule.get("start_hour") or "00:00"
        hour, minute = map(int, str(start).split(":"))
        cursor = hour * 60 + minute
        slots = []
        while cursor < 24 * 60:
            slots.append(f"{cursor // 60:02d}:{cursor % 60:02d}")
            cursor += interval * 60
        return slots
    slots = [str(s).strip() for s in (schedule.get("slots") or ["04:00", "20:00"])]
    return sorted(s for s in slots if len(s) == 5 and s[2] == ":")


def due_slots(config: dict, database, now: datetime | None = None) -> list[str]:
    """Créneaux manuels du jour déjà atteints et pas encore publiés (chronologique)."""
    now = now or datetime.now()
    today = now.date().isoformat()
    current = now.strftime("%H:%M")
    return [
        slot for slot in manual_slots(config)
        if slot <= current and not database.manual_slot_done(today, slot)
    ]


def run_manual(config: dict, service, logger, dry_run: bool = False) -> dict:
    """Un tour du planificateur manuel : publie les fichiers en attente aux
    créneaux dus. Ne fait RIEN si le dossier assets/pending est vide.

    Retourne un dict récapitulatif (idle / published / failed).
    """
    from .manual import delete_pending, generate_caption, list_pending

    now = datetime.now()
    files = [
        f for f in list_pending(config)
        if f["kind"] in ("image", "video")
    ]
    if not files:
        return {"status": "idle", "message": "Aucun contenu en attente."}

    # On ne publie que des fichiers dont la copie est terminée (mtime > 60 s).
    files = [
        f for f in files
        if (now.timestamp() - _mtime(config, f["name"])) > 60
    ]
    if not files:
        return {"status": "idle", "message": "Fichier(s) en cours de copie, nouvel essai au prochain tour."}
    files.sort(key=lambda f: _mtime(config, f["name"]))

    due = due_slots(config, service.database, now)
    if not due:
        return {"status": "idle", "message": "Aucun créneau dû pour l'instant."}

    networks = config.get("manual_schedule", {}).get("networks") or []
    today = now.date().isoformat()
    results = []
    for slot in due:
        if not files:
            break
        source = files.pop(0)
        try:
            caption = generate_caption(source["name"])
        except Exception as exc:
            logger.warning("Génération de légende échouée pour %s : %s", source["name"], exc)
            caption = source["name"]
        result = service.publish_manual(
            media_path=str(_path(config, source["name"])),
            caption=caption,
            scheduled_for=f"{today}T{slot}",
            dry_run=dry_run,
            networks=networks or None,
            filename=source["name"],
        )
        status = result.get("status")
        if not dry_run and status in ("published", "partial"):
            delete_pending(config, source["name"])
        results.append({"slot": slot, "file": source["name"], "status": status, "id": result.get("id")})
        logger.info(
            "Manuel %s: %s -> %s (id=%s)", slot, source["name"], status, result.get("id")
        )
        if not dry_run and status in ("failed", "error"):
            break  # on laisse les autres fichiers pour les tours suivants

    success_states = ("published", "partial")
    if dry_run:
        success_states += ("prepared",)
    overall = "published" if any(r["status"] in success_states for r in results) else "failed"
    return {"status": overall, "results": results}


def _path(config: dict, name: str):
    from .manual import pending_dir

    return pending_dir(config) / name


def _mtime(config: dict, name: str) -> float:
    try:
        return _path(config, name).stat().st_mtime
    except OSError:
        return time.time()
