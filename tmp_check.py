import sys

sys.path.insert(0, ".")
from src.config import load_config, absolute_path
from src.video import probe_duration
from src.manual import list_pending
from src.secrets import get_secret
import requests

cfg = load_config()
pending = list_pending(cfg)
print("--- DUREES (5 premieres videos pending) ---")
for p in pending[:5]:
    path = absolute_path(cfg["paths"].get("pending", "assets/pending")) / p["name"]
    try:
        dur = probe_duration(path)
        print(f"  {p['name'][:60]} -> {dur:.1f}s ({'LONGUE' if dur > 60 else 'courte'})")
    except Exception as exc:
        print(f"  {p['name'][:60]} -> ERREUR {exc}")

print("\n--- POST FACEBOOK 235 existe-t-il ? ---")
try:
    r = requests.get(
        f"https://graph.facebook.com/{cfg['facebook']['api_version']}/2269443887290824",
        params={"fields": "id,created_time,type", "access_token": get_secret("facebook_page_token")},
        timeout=30,
    )
    print("  HTTP", r.status_code, "|", r.text[:300])
except Exception as exc:
    print("  ERREUR", exc)