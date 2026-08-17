import sys, time

sys.path.insert(0, ".")
from src.config import load_config
from src.database import HistoryDatabase
from src.content import ContentGenerator

cfg = load_config()
db = HistoryDatabase(cfg["paths"]["database"])
gen = ContentGenerator(db, cfg)
exclusions = {field: sorted(db.recent_values(field))[-180:] for field in ("title", "topic", "verse_reference", "cta", "decor")}
t0 = time.time()
try:
    c = gen._llm(exclusions, hook_type=gen._pick_hook_type(), pillar="Dignité")
    print("LLM OK:", round(time.time() - t0, 1), "s")
    print("TITRE:", c.title)
    print("PROVIDER:", getattr(gen, "_last_provider", None))
except Exception as e:
    print("LLM FAIL:", round(time.time() - t0, 1), "s")
    import traceback
    traceback.print_exc()
    print(str(e)[:1000])