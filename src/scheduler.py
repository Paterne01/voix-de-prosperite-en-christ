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

import random
from datetime import datetime

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

PUBLISH_PREFIX = "format_"
MANUAL_JOB_ID = "manual_tick"


def pick_random_time_in_window(window_str: str) -> datetime:
    """Tire un moment aléatoire dans une plage 'HH:MM-HH:MM'."""
    try:
        start_s, end_s = window_str.split("-")
        sh, sm = map(int, start_s.strip().split(":"))
        eh, em = map(int, end_s.strip().split(":"))
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        if end_min <= start_min:
            end_min = start_min + 60
        chosen = random.randint(start_min, end_min)
        now = datetime.now()
        return now.replace(hour=chosen // 60, minute=chosen % 60, second=0, microsecond=0)
    except Exception:
        return datetime.now()


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


def run_window_job(config: dict, window: str) -> None:
    """Job pour une fenêtre anti-shadowban : publie le format dû à l'heure tirée."""
    from src.jobs import run_slot
    from src.logging_setup import setup_logging
    from src.service import PublicationService

    logger = setup_logging(config)
    service = PublicationService(config, logger)
    # Détermine le format selon l'heure de la fenêtre (matin→video, midi→declaration, soir→video)
    try:
        start_s = window.split("-")[0].strip()
        h = int(start_s.split(":")[0])
        fmt_name = "video" if h < 12 or h >= 18 else "declaration"
        # Trouve le format actif correspondant
        for fmt in service.database.list_formats(only_active=True):
            if service.normalize_format(fmt["output_type"]) == fmt_name:
                slot = f"{h:02d}:00"  # slot fictif pour le log
                scheduled_for = f"{datetime.now().date().isoformat()}T{window}"
                result = run_slot(config, service, fmt, slot, scheduled_for)
                logger.info("Fenêtre %s (%s) -> %s", window, fmt["name"], result.get("status"))
                return
        logger.warning("Aucun format trouvé pour fenêtre %s", window)
    except Exception as exc:
        logger.exception("Fenêtre %s échouée : %s", window, exc)


def run_learning_job(config: dict) -> None:
    from src.learning import run_learning_cycle
    from src.logging_setup import setup_logging
    logger = setup_logging(config)
    from src.config import absolute_path
    db_path = str(absolute_path(config["paths"]["database"]))
    try:
        run_learning_cycle(db_path)
        logger.info("Learning cycle terminé")
    except Exception as exc:
        logger.exception("Learning échoué : %s", exc)


def run_recycling_job(config: dict) -> None:
    from src.recycler import run_recycling
    from src.logging_setup import setup_logging
    logger = setup_logging(config)
    from src.config import absolute_path
    db_path = str(absolute_path(config["paths"]["database"]))
    try:
        n = run_recycling(db_path)
        logger.info("Recyclage : %s posts planifiés", n)
    except Exception as exc:
        logger.exception("Recyclage échoué : %s", exc)


def run_weekly_batch_job(config: dict) -> None:
    from src.batch_generator import generate_week_batch
    from src.logging_setup import setup_logging
    logger = setup_logging(config)
    from src.config import absolute_path
    db_path = str(absolute_path(config["paths"]["database"]))
    try:
        n = generate_week_batch(db_path)
        logger.info("Batch hebdo généré : %s posts", n)
    except Exception as exc:
        logger.exception("Batch hebdo échoué : %s", exc)


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

        self.scheduler.remove_all_jobs()
        # Si schedule_windows est défini, on l'utilise (anti-shadowban) : un job
        # par fenêtre à un moment aléatoire tiré au lancement.
        windows = self.config.get("schedule_windows")
        if isinstance(windows, list) and windows:
            for idx, win in enumerate(windows):
                try:
                    dt = pick_random_time_in_window(win)
                    self.scheduler.add_job(
                        run_window_job,
                        "cron",
                        hour=dt.hour,
                        minute=dt.minute,
                        args=[self.config, win],
                        id=f"window_{idx}_{win}",
                        replace_existing=True,
                        name=f"Fenêtre {win}",
                    )
                    self.logger.info("Fenêtre %s -> %02d:%02d", win, dt.hour, dt.minute)
                except Exception as exc:
                    self.logger.warning("Fenêtre invalide %r : %s", win, exc)
        else:
            formats = PublicationService(self.config, setup_logging(self.config)).database.list_formats(only_active=True)
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
        # Batch hebdomadaire : dimanche 21h
        try:
            self.scheduler.add_job(
                run_weekly_batch_job,
                "cron",
                day_of_week="sun",
                hour=21,
                minute=0,
                args=[self.config],
                id="weekly_batch",
                replace_existing=True,
                name="Génération batch hebdomadaire",
            )
        except Exception:
            pass
        # Recyclage : tous les 14 jours
        try:
            self.scheduler.add_job(
                run_recycling_job,
                "interval",
                days=14,
                args=[self.config],
                id="recycler",
                replace_existing=True,
                name="Recyclage top performers",
            )
        except Exception:
            pass
        # Learning : lundi 06h
        try:
            self.scheduler.add_job(
                run_learning_job,
                "cron",
                day_of_week="mon",
                hour=6,
                minute=0,
                args=[self.config],
                id="learning_cycle",
                replace_existing=True,
                name="Learning loop",
            )
        except Exception:
            pass

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