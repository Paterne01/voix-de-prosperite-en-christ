import sys

sys.path.insert(0, ".")
from src.config import load_config
from src.secrets import get_secret
import requests

cfg = load_config()
token = get_secret("facebook_page_token")

for pid in ("2269443887290824", "1601156165016204"):
    try:
        r = requests.get(
            f"https://graph.facebook.com/{cfg['facebook']['api_version']}/{pid}",
            params={"fields": "id,created_time,permalink_url,status", "access_token": token},
            timeout=30,
        )
        print(pid, "->", r.status_code, "|", r.text[:400])
    except Exception as exc:
        print(pid, "-> ERREUR", exc)

print("\n--- Derniers posts de la page (video) ---")
try:
    r = requests.get(
        f"https://graph.facebook.com/{cfg['facebook']['api_version']}/{cfg['page_id']}/videos",
        params={"fields": "id,created_time,length,title", "access_token": token, "limit": 5},
        timeout=30,
    )
    print("HTTP", r.status_code, "|", r.text[:800])
except Exception as exc:
    print("ERREUR", exc)