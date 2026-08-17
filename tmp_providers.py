import sys

sys.path.insert(0, ".")
from src.config import load_config
from src.llm import ordered_providers, check_provider

cfg = load_config()
provs = ordered_providers(cfg)
print("ORDRE:", [p.name for p in provs])
for p in provs:
    ok, msg = check_provider(cfg, p.name)
    print(("OK   " if ok else "FAIL ") + f"  {msg[:120]}")