from __future__ import annotations

import time
from datetime import datetime

# Fenêtre autour de l'heure d'un créneau pendant laquelle il est « actif » :
# quelques minutes AVANT (l'heure approche) et quelques minutes APRÈS (tolérance
# de dérive du tick toutes les 5/10 minutes). Un créneau passé depuis longtemps
# n'est JAMAIS rattrapé : les fichiers déposés en pleine journée attendent la
# prochaine heure de publication dans assets/pending.
SLOT_EARLY_MINUTES = 5
SLOT_GRACE_MINUTES = 20


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


def slot_due_now(config: dict, database, now: datetime | None = None) -> str | None:
    """Renvoie le créneau manuel à publier MAINTENANT, ou None.

    Un créneau n'est publié que si l'heure courante tombe dans la fenêtre qui
    entoure son horaire (le créneau « approche » ou vient de sonner). Déposer
    un fichier en pleine journée ne déclenche donc RIEN : le fichier attend la
    prochaine heure de publication. Un créneau déjà publié est ignoré (anti-
    doublon) et on passe au suivant.
    """
    now = now or datetime.now()
    today = now.date().isoformat()
    current_min = now.hour * 60 + now.minute
    for slot in manual_slots(config):
        try:
            hour, minute = map(int, slot.split(":"))
        except ValueError:
            continue
        slot_min = hour * 60 + minute
        if slot_min - SLOT_EARLY_MINUTES <= current_min <= slot_min + SLOT_GRACE_MINUTES:
            if not database.manual_slot_done(today, slot):
                return slot
    return None


def _acquire_manual_lock(timeout_s: int = 280) -> bool:
    """Verrou fichier pour empêcher deux ticks manuels concurrents de publier
    2 fichiers pour le même créneau (APScheduler toutes les 5 min + tâche
    Windows toutes les 10 min dans la fenêtre 19:55-20:20). Le verrou expire
    après `timeout_s` pour éviter un blocage permanent si un tick plante."""
    from pathlib import Path
    from src.config import absolute_path

    try:
        lock = absolute_path("Logs/manual.lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        if lock.exists():
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = timeout_s + 1
            if age < timeout_s:
                return False
            try:
                lock.unlink()
            except OSError:
                pass
        try:
            lock.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            return False
        return True
    except Exception:
        return True


def _release_manual_lock() -> None:
    from pathlib import Path
    from src.config import absolute_path

    try:
        lock = absolute_path("Logs/manual.lock")
        if lock.exists():
            lock.unlink()
    except OSError:
        pass


def run_manual(config: dict, service, logger, dry_run: bool = False) -> dict:
    """Un tour du planificateur manuel : à l'heure d'un créneau, publie LE
    fichier le plus ancien en attente, puis passe au suivant au créneau suivant.

    - Les fichiers restent dans assets/pending tant que l'heure n'est pas venue.
    - Un SEUL fichier (image ou vidéo) est traité par créneau, du plus ancien au
      plus récent (date d'ajout = mtime du fichier).
    - La légende est générée depuis le nom du fichier (Facebook) et sert de
      description YouTube/TikTok ; YouTube reçoit aussi titre + tags (IA).
    - Une fois la publication confirmée, le fichier et les résidus sont nettoyés.
    - À l'heure du créneau sans aucun fichier disponible : rien ne se passe.

    Retourne un dict récapitulatif (idle / published / failed).
    """
    from .manual import delete_pending, generate_caption, list_pending

    now = datetime.now()
    # Garde-fou anti-concurrence : un seul tick manuel à la fois. Sans cela,
    # APScheduler (5 min) + tâche Windows (10 min) dans la fenêtre 20:00
    # publiaient 2 fichiers distincts pour le même créneau → 2 posts YouTube.
    if not dry_run and not _acquire_manual_lock():
        return {"status": "idle", "message": "Tick manuel déjà en cours (verrou actif)."}
    files = [
        f for f in list_pending(config)
        if f["kind"] in ("image", "video")
    ]
    if not files:
        return {"status": "idle", "message": "Aucun contenu en attente."}

    # Anti-doublon : un fichier déjà publié avec succès (ou en cours de
    # publication par un tour qui se chevauche) n'est JAMAIS republié.
    already = [
        f for f in files
        if service.database.manual_source_published(f["name"])
    ]
    for stale in already:
        logger.warning(
            "Fichier déjà publié %r ignoré (anti-doublon), nettoyage.", stale["name"]
        )
        delete_pending(config, stale["name"])
    files = [f for f in files if f not in already]
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

    slot = slot_due_now(config, service.database, now)
    if not slot:
        return {"status": "idle", "message": "Aucune heure de publication atteinte — fichiers en attente du prochain créneau."}

    networks = config.get("manual_schedule", {}).get("networks") or []
    today = now.date().isoformat()
    # Double vérification juste avant de consommer le fichier : si un autre
    # processus a réservé le créneau entre-temps (pending créé), on s'arrête.
    if not dry_run and service.database.manual_slot_done(today, slot):
        _release_manual_lock()
        return {"status": "idle", "message": f"Créneau {slot} déjà réservé — doublon évité."}
    source = files.pop(0)
    try:
        caption = generate_caption(source["name"])
    except Exception as exc:
        logger.warning("Génération de légende échouée pour %s : %s", source["name"], exc)
        caption = source["name"]
    try:
        result = service.publish_manual(
            media_path=str(_path(config, source["name"])),
            caption=caption,
            scheduled_for=f"{today}T{slot}",
            dry_run=dry_run,
            networks=networks or None,
            filename=source["name"],
        )
    finally:
        if not dry_run:
            _release_manual_lock()
    status = result.get("status")
    if not dry_run and status in ("published", "partial"):
        delete_pending(config, source["name"])
    logger.info(
        "Manuel %s: %s -> %s (id=%s)", slot, source["name"], status, result.get("id")
    )

    success_states = ("published", "partial")
    if dry_run:
        success_states += ("prepared",)
    overall = "published" if status in success_states else "failed"
    return {
        "status": overall,
        "results": [{"slot": slot, "file": source["name"], "status": status, "id": result.get("id")}],
    }


def _path(config: dict, name: str):
    from .manual import pending_dir

    return pending_dir(config) / name


def _mtime(config: dict, name: str) -> float:
    try:
        return _path(config, name).stat().st_mtime
    except OSError:
        return time.time()
