import sqlite3, json, random
from datetime import datetime, timedelta
from pathlib import Path

HOOK_VARIATIONS = [
  "Tu l'as peut-être manqué la première fois : {}",
  "Une vérité qui change tout : {}",
  "Beaucoup ne l'ont jamais entendu : {}",
  "Rappel important pour toi aujourd'hui : {}",
  "Ce message revient parce qu'il en valait la peine : {}",
]

def find_recyclable(db_path: str, min_views: int = 50, days_old: int = 30) -> list:
    """
    Trouve les posts avec bonnes performances publiés il y a >30 jours
    et non encore recyclés.
    """
    conn = sqlite3.connect(db_path)
    cutoff = (datetime.now() - timedelta(days=days_old)).isoformat()
    # Utilise publications au lieu de posts
    rows = conn.execute(
        """SELECT id, caption, comment_text, hashtags, title, pillar, format, views_total, likes_total
           FROM publications
           WHERE created_at < ?
             AND views_total >= ?
             AND recycled_from IS NULL
             AND status = 'published'
           ORDER BY views_total DESC
           LIMIT 5""",
        (cutoff, min_views)
    ).fetchall()
    conn.close()
    return rows

def recycle_post(db_path: str, original_id: int, row_data: tuple, fmt: str = "video"):
    """
    Prépare un post recyclé avec hook varié et l'insère dans content_queue.
    row_data est le tuple retourné par find_recyclable.
    """
    _id, caption, comment_text, hashtags, title, pillar, fmt_orig, views, likes = row_data
    # Construire un content_json minimal pour la queue
    # On varie le hook/caption
    variation_template = random.choice(HOOK_VARIATIONS)
    # Utiliser le caption comme hook de base
    new_caption = variation_template.format(caption[:80] if caption else title)
    content = {
        "title": title,
        "caption": new_caption,
        "comment_text": comment_text,
        "hashtags": hashtags.split() if hashtags else [],
        "pillar": pillar,
        "recycled": True,
        "recycled_from": _id,
        "original_title": title,
    }
    scheduled_for = (datetime.now() + timedelta(days=random.randint(1, 3))).replace(
        hour=random.choice([8, 13, 18]),
        minute=random.randint(0, 30),
        second=0,
        microsecond=0
    ).isoformat()

    conn = sqlite3.connect(db_path)
    # Assurer que content_queue existe
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
    conn.execute(
        """INSERT INTO content_queue
           (format, pillar, scheduled_for, content_json, status, platform)
           VALUES (?,?,?,?,?,?)""",
        (fmt_orig or fmt, pillar or "", scheduled_for,
         json.dumps(content, ensure_ascii=False), "pending", "facebook")
        # Recycler sur Facebook seulement (plateforme à plus grand potentiel viral)
    )
    conn.commit()
    conn.close()
    return scheduled_for

def run_recycling(db_path: str):
    """Point d'entrée : trouve et planifie les recyclages."""
    candidates = find_recyclable(db_path, min_views=30)
    count = 0
    for row in candidates[:2]:  # max 2 recyclages/cycle
        try:
            # row est tuple de 9 éléments, on passe le format
            fmt = row[5] if len(row) > 5 and row[5] else "video"
            scheduled = recycle_post(db_path, row[0], row, fmt)
            print(f"[RECYCLER] Post {row[0]} ({row[7]} vues) planifié pour {scheduled}")
            count += 1
        except Exception as e:
            print(f"[RECYCLER] Erreur recyclage {row[0]}: {e}")
    return count

if __name__ == "__main__":
    import sys
    from src.config import load_config, absolute_path
    config = load_config()
    db_path = str(absolute_path(config["paths"]["database"]))
    print(run_recycling(db_path))
