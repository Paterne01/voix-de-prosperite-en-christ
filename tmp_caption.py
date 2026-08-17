import sys

sys.path.insert(0, ".")
from src.config import load_config, absolute_path
from src.database import HistoryDatabase

cfg = load_config()
db = HistoryDatabase(absolute_path(cfg["paths"]["database"]))
for pid in (234, 235):
    r = db.get(pid)
    print("ID", pid, "| status:", r.get("status"))
    print("  caption:", repr(r.get("caption"))[:300])
    print("  comment_text:", repr(r.get("comment_text"))[:200])
    print("  youtube_description:", repr(r.get("youtube_description"))[:200])
    print()