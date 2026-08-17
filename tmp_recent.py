import sys

sys.path.insert(0, ".")
from src.config import load_config, absolute_path
from src.database import HistoryDatabase
from src.manual import list_pending

cfg = load_config()
db = HistoryDatabase(absolute_path(cfg["paths"]["database"]))
rows = db.recent(15)
for r in rows:
    print(
        r["id"], "|", r["format"], "|", r["status"],
        "|", (r.get("title") or "")[:45],
        "| fb:", r.get("facebook_post_id") or "-",
        "| yt:", r.get("youtube_video_id") or "-",
    )
print("\nPENDING:")
for p in list_pending(cfg):
    print(" ", p["name"], "|", p["kind"], "|", p["size"], "B |", p["modified"])