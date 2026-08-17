import sys

sys.path.insert(0, ".")
from src.config import load_config, absolute_path
from src.database import HistoryDatabase

cfg = load_config()
db = HistoryDatabase(absolute_path(cfg["paths"]["database"]))
for pid in (234, 235, 233, 236, 237, 238):
    r = db.get(pid)
    if not r:
        continue
    print("ID", pid)
    for k in ("title", "status", "error", "facebook_post_id", "facebook_url", "youtube_video_id", "format", "format_name", "scheduled_for", "source_filename"):
        v = r.get(k)
        if v:
            print("   ", k, "=", str(v)[:120])
    print()