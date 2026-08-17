import sys, time

sys.path.insert(0, ".")
from src.config import load_config
from src.database import HistoryDatabase
from src.content import ContentGenerator

cfg = load_config()
db = HistoryDatabase(cfg["paths"]["database"])
gen = ContentGenerator(db)
t0 = time.time()
exclusions = {
    field: set(db.recent_values(field, days=90))
    for field in ("title", "topic", "verse_reference", "cta", "decor")
}
content = gen.generate(pillar="Dignité", prompt=None)
t1 = time.time()
print("DUREE:", round(t1 - t0, 1), "s")
print("LOCAL_FALLBACK:", getattr(content, "local_fallback", False))
print("TITRE:", content.title)
print("PROVIDER:", getattr(content, "provider", None))