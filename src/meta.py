from __future__ import annotations

import time

import requests


class MetaPublisher:
    def __init__(self, config: dict, token: str, logger):
        self.config = config
        self.token = token
        self.logger = logger
        self.base = f"https://graph.facebook.com/{config['facebook']['api_version']}"

    def validate(self) -> dict:
        response = requests.get(
            f"{self.base}/{self.config['page_id']}",
            params={
                "fields": "id,name",
                "access_token": self.token,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def publish(
        self, image_path, caption: str, comment: str, *, with_comment: bool = True
    ) -> tuple[str, str | None, str | None]:
        retries = int(self.config["facebook"].get("max_retries", 3))

        for attempt in range(retries):
            try:
                with open(image_path, "rb") as image:
                    response = requests.post(
                        f"{self.base}/{self.config['page_id']}/photos",
                        data={
                            "caption": caption,
                            "access_token": self.token,
                        },
                        files={"source": image},
                        timeout=90,
                    )

                response.raise_for_status()

                payload = response.json()

                post_id = payload.get("post_id") or payload.get("id")

                if not post_id:
                    raise RuntimeError(f"Réponse Meta sans identifiant : {payload}")

                comment_url = None
                if with_comment and comment.strip():
                    comment_response = requests.post(
                        f"{self.base}/{post_id}/comments",
                        data={
                            "message": comment,
                            "access_token": self.token,
                        },
                        timeout=45,
                    )

                    comment_response.raise_for_status()
                    comment_url = f"https://www.facebook.com/{post_id}?comment_id={comment_response.json().get('id')}"

                return post_id, f"https://www.facebook.com/{post_id}", comment_url

            except requests.RequestException as exc:

                if attempt == retries - 1:

                    body = ""

                    try:
                        if exc.response is not None:
                            body = exc.response.text
                    except Exception:
                        body = "Impossible de lire la réponse de Meta."

                    raise RuntimeError(
                        f"""
Publication Meta impossible après {retries} essais.

Erreur HTTP :
{exc}

Réponse complète de Meta :
{body}
"""
                    ) from exc

                self.logger.warning(
                    "Échec Meta (%s/%s), nouvel essai : %s",
                    attempt + 1,
                    retries,
                    exc,
                )

                time.sleep(2 ** attempt)

        raise AssertionError("Boucle de publication inattendue")