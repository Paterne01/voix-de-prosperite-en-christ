import json, sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Imports adaptés au projet réel
try:
    from src.content import ContentGenerator
    from src.content_declarations import DeclarationGenerator
except ImportError:
    ContentGenerator = None
    DeclarationGenerator = None

WEEKLY_PLAN = [
  # (jour_semaine 0=lundi, format, heure, pilier_override_ou_None)
  (0, "A", "08:15", None),  (0, "B", "12:30", None),
  (1, "A", "08:45", None),  (1, "B", "13:00", None),
  (2, "A", "09:00", None),  (2, "B", "12:15", None),
  (3, "A", "08:30", None),  (3, "B", "13:30", None),
  (4, "A", "08:00", None),  (4, "B", "12:00", None),
  (5, "A", "10:00", None),  (5, "B", "14:00", None),
  (6, "B", "11:00", None),  # dimanche : 1 seul post
]
# Max 2 posts/jour respecté dans ce plan

def _get_db_path(db_path: str | None = None) -> str:
    if db_path:
        return db_path
    try:
        from src.config import load_config, absolute_path
        cfg = load_config()
        return str(absolute_path(cfg.get("paths", {}).get("database", "BaseDeDonnées/voix_prosperite.sqlite3")))
    except Exception:
        return "BaseDeDonnées/voix_prosperite.sqlite3"

def generate_week_batch(db_path: str | None = None, start_date: datetime | None = None):
    """
    Génère et stocke 7 jours de contenu dans content_queue.
    start_date = prochain lundi si None.
    """
    db_path = _get_db_path(db_path)
    if start_date is None:
        today = datetime.now().date()
        days_ahead = 7 - today.weekday() if today.weekday() != 0 else 0
        if days_ahead == 7:
            days_ahead = 7
        # Si aujourd'hui est lundi, on génère pour lundi prochain
        if today.weekday() == 0:
            days_ahead = 7
        else:
            days_ahead = (7 - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
        start_date = datetime.combine(today + timedelta(days=days_ahead), datetime.min.time())

    # Assurer que les tables existent
    conn = sqlite3.connect(db_path)
    # Créer la table si elle n'existe pas (au cas où l'app n'a pas redémarré)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS content_queue (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          format TEXT NOT NULL,
          pillar TEXT NOT NULL,
          scheduled_for TEXT NOT NULL,
          content_json TEXT NOT NULL,
          media_path TEXT,
          status TEXT DEFAULT 'pending',
          platform TEXT NOT NULL,
          created_at TEXT DEFAULT (datetime('now')),
          published_at TEXT
        )
    """)
    conn.commit()

    # Charger config et DB pour la génération
    try:
        from src.config import load_config, absolute_path
        from src.database import HistoryDatabase
        config = load_config()
        db = HistoryDatabase(absolute_path(config["paths"]["database"]))
    except Exception as e:
        print(f"[BATCH] Erreur chargement config/DB : {e}")
        conn.close()
        return 0

    generated = 0

    for (weekday, fmt, heure, pilier) in WEEKLY_PLAN:
        pub_date = start_date + timedelta(days=weekday)
        h, m = map(int, heure.split(":"))
        scheduled_for = pub_date.replace(hour=h, minute=m, second=0).isoformat()

        # Éviter les doublons si batch déjà généré pour cette date
        existing = conn.execute(
            "SELECT id FROM content_queue WHERE scheduled_for=? AND status='pending'",
            (scheduled_for,)
        ).fetchone()
        if existing:
            continue

        try:
            if fmt == "A":
                gen = ContentGenerator(db, config)
                # Générer avec pilier du jour si pas d'override
                from src.config import weekday_pillar
                pillar_to_use = pilier or weekday_pillar(config, pub_date)
                content = gen.generate(pillar=pillar_to_use)
                cdict = content.to_dict()
                # Ajouter le pilier utilisé
                cdict["pillar"] = pillar_to_use or content.pillar
            else:
                gen = DeclarationGenerator(db, config)
                from src.config import weekday_pillar
                pillar_to_use = pilier or weekday_pillar(config, pub_date)
                content = gen.generate(pillar=pillar_to_use)
                cdict = content.to_dict()
                cdict["pillar"] = pillar_to_use or content.pillar

            conn.execute(
                """INSERT INTO content_queue
                   (format, pillar, scheduled_for, content_json, status, platform)
                   VALUES (?,?,?,?,?,?)""",
                (fmt, cdict.get("pillar",""), scheduled_for,
                 json.dumps(cdict, ensure_ascii=False), "pending", "both")
            )
            conn.commit()
            generated += 1
            print(f"[BATCH] Généré {fmt} pour {scheduled_for} ({cdict.get('pillar','')})")
        except Exception as e:
            print(f"[BATCH] Erreur {scheduled_for} : {e}")
            import traceback; traceback.print_exc()

    conn.close()
    return generated
