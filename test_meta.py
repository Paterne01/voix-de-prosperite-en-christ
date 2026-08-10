from src.config import load_config
from src.secrets import get_secret
import requests

config = load_config()
token = get_secret("facebook_page_token")

url = f"https://graph.facebook.com/{config['facebook']['api_version']}/{config['page_id']}"

response = requests.get(
    url,
    params={
        "fields": "id,name",
        "access_token": token,
    },
)

print("STATUS :", response.status_code)
print(response.text)