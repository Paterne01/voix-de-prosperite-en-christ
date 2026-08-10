"""YouTube OAuth 2.0 — authenticates once and saves credentials.

Prérequis
---------
1. Allez sur https://console.cloud.google.com/apis/credentials
2. Créez un **ID client OAuth** (type Application de bureau).
3. Téléchargez le JSON et placez-le dans  assets/youtube_client_secret.json
4. Lancez ce script :
       python scripts/youtube_auth_setup.py

Le token est sauvegardé dans BaseDeDonnées/youtube_token.pickle.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRETS = ROOT / "assets" / "youtube_client_secret.json"
TOKEN_PATH = ROOT / "BaseDeDonnées" / "youtube_token.pickle"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def main() -> None:
    if not CLIENT_SECRETS.exists():
        print(
            "Fichier introuvable : assets/youtube_client_secret.json\n\n"
            "1. Allez sur https://console.cloud.google.com/apis/credentials\n"
            "2. Créez un ID client OAuth (type Application de bureau)\n"
            "3. Téléchargez le JSON et placez-le dans :\n"
            f"   {CLIENT_SECRETS}\n"
        )
        return

    # Parse le JSON pour rassurer l'utilisateur sur la bonne valeur du client_secret
    try:
        data = json.loads(CLIENT_SECRETS.read_text(encoding="utf-8"))
        if "installed" in data:
            print("Client OAuth : Application de bureau (desktop) OK")
        else:
            print("Attention : ce client ne semble pas être de type 'Application de bureau'.")
    except Exception as exc:
        print(f"Fichier JSON illisible : {exc}")
        return

    # port=0 : l'OS choisit un port libre. Pour un client 'Application de bureau',
    # Google accepte les URI de boucle locale (localhost) avec n'importe quel port,
    # donc aucun reenregistrement dans la console n'est necessaire.
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TOKEN_PATH.open("wb") as f:
        pickle.dump(creds, f)

    print(f"Authentification réussie ! Token sauvegardé : {TOKEN_PATH}")


if __name__ == "__main__":
    main()
