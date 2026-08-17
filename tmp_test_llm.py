import sys

sys.path.insert(0, ".")
from src.config import load_config
from src.database import HistoryDatabase
from src.content import ContentGenerator

cfg = load_config()
db = HistoryDatabase(cfg["paths"]["database"])
gen = ContentGenerator(db)
exclusions = {field: sorted(db.recent_values(field))[-180:] for field in ("title", "topic", "verse_reference", "cta", "decor")}
try:
    c = gen._llm(exclusions, hook_type=gen._pick_hook_type(), pillar="Dignité")
    print("LLM OK:", c.title)
except Exception as e:
    import traceback
    traceback.print_exc()
    print("LLM FAIL:", type(e).__name__)
    print(str(e)[:1500])