import sys

sys.path.insert(0, ".")
from src.config import load_config, absolute_path
from src.database import HistoryDatabase

cfg = load_config()
db = HistoryDatabase(absolute_path(cfg["paths"]["database"]))
rows = db.recent(15)
for r in rows:
    fmt = r.get("format") or r.get("format_name") or ""
    print(r["id"], (r["created_at"] or "")[:19], "|", (r["scheduled_for"] or "")[:16], "|", str(r["status"]), "|", str(fmt)[:28], "|", (r["title"] or "")[:40])