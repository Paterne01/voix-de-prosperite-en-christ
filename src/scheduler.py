"""Planificateur intégré au serveur Flask (APScheduler).

Remplace le recours systématique au Planificateur de tâches Windows : les
créneaux de publication sont recalculés à partir de la table `post_formats`
(jeu de données unique) et persistés dans SQLite (`apscheduler_jobs`).
La CLI `run_job.py` reste disponible pour le dry-run et le rattrapage manuel.

Les cibles de job sont des fonctions module-level prenant des arguments
picklables (config, fmt_id, slot) : APScheduler sérialise les jobs dans la
base, il faut donc éviter d'y emporter des objets lourds (service, logger).
"""

from __future__ import annotations

from datetime import datetime

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

PUBLISH_PREFIX = "format_"
MANUAL_JOB_ID = "manual_tick"


# --- Cibles d'exécution (module-level, picklables) --------------------------------

def run_format_job(config: dict, fmt_id: int, slot: str) -> None:
    from src.jobs import run_slot
    from src.logging_setup import setup_logging
    from src.service import PublicationService

    logger = setup_logging(config)
    service = PublicationService(config, logger)
    fmt = service.database.get_format(fmt_id)
    if not fmt:
        logger.warning("Format #%s introuvable (job %s) — rien à publier.", fmt_id, slot)
        return
    # Garde-fou anti-doublon : si un contenu a déjà été publié pour ce créneau
    # aujourd'hui (que ce soit par la CLI, le rattrapage ou ce scheduler), on
    # ne publie pas deux fois.
    if not service.database.needs_catch_up(slot):
        logger.info("Anti-doublon : %s @ %s déjà publié, skip.", fmt["name"], slot)
        return
    scheduled_for = f"{datetime.now().date().isoformat()}T{slot}"
    result = run_slot(config, service, fmt, slot, scheduled_for)
    logger.info("Job %s @ %s -> %s", fmt["name"], slot, result.get("status"))


def run_manual_job(config: dict) -> None:
    from src.jobs import run_manual_tick
    from src.logging_setup import setup_logging
    from src.service import PublicationService

    logger = setup_logging(config)
    service = PublicationService(config, logger)
    result = run_manual_tick(config, service, logger)
    if result.get("status") != "idle":
        logger.info("Tick manuel -> %s", result)


# --- Planificateur ---------------------------------------------------------------

class PostScheduler:
    def __init__(self, config: dict, logger) -> None:
        self.config = config
        self.logger = logger
        from src.config import absolute_path

        jobstore = SQLAlchemyJobStore(
            url=f"sqlite:///{absolute_path(config['paths']['database']).as_posix()}"
        )
        self.scheduler = BackgroundScheduler(
            jobstores={"default": jobstore},
            timezone=config.get("timezone", "Africa/Nairobi"),
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 3600,
            },
        )

    def start(self, config: dict | None = None) -> None:
        if config is not None:
            self.config = config
        self.scheduler.start()
        self.sync()

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def sync(self, config: dict | None = None) -> None:
        """Recrée les jobs de publication + la boucle manuelle depuis les
        formats actifs de la BD. À rappeler après chaque modif d'un format
        ou des réglages."""
        if config is not None:
            self.config = config
        from src.logging_setup import setup_logging
        from src.service import PublicationService

        formats = PublicationService(self.config, setup_logging(self.config)).database.list_formats(only_active=True)
        self.scheduler.remove_all_jobs()
        for fmt in formats:
            self._add_format_jobs(fmt)
        self.scheduler.add_job(
            run_manual_job,
            IntervalTrigger(minutes=5),
            args=[self.config],
            id=MANUAL_JOB_ID,
            replace_existing=True,
            name="Publication manuelle (fichiers importés)",
        )

    def _add_format_jobs(self, fmt: dict) -> None:
        for slot in fmt["schedule"]:
            try:
                hour, minute = map(int, slot.split(":"))
            except ValueError:
                self.logger.warning("Créneau invalide %r pour %s", slot, fmt["name"])
                continue
            self.scheduler.add_job(
                run_format_job,
                "cron",
                hour=hour,
                minute=minute,
                args=[self.config, fmt["id"], slot],
                id=f"{PUBLISH_PREFIX}{fmt['id']}_{slot}",
                replace_existing=True,
                name=f"{fmt['name']} @ {slot}",
            )

    def scheduled_jobs(self) -> list[dict]:
        jobs = []
        for job in self.scheduler.get_jobs():
            schedules = []
            if job.trigger and getattr(job.trigger, "fields", None):
                for field in job.trigger.fields:
                    schedules.append(f"{field.name}={','.join(map(str, field.expressions))}")
            jobs.append({
                "id": job.id,
                "name": job.name,
                "trigger": str(job.trigger),
                "next": job.next_run_time.isoformat(timespec="seconds") if job.next_run_time else None,
                "schedules": schedules,
            })
        return jobs