import sys

sys.path.insert(0, ".")
from src.config import load_config
from src.secrets import get_secret

cfg = load_config()
ai = cfg["ai"]
for n, spec in ai["providers"].items():
    sec = spec.get("api_key_secret")
    have = bool(get_secret(sec)) if sec else True
    print(f"{n:12} key={'OK' if have else 'NO'}")