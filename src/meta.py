from __future__ import annotations

import json
import time
from datetime import datetime

import requests


def explain_graph_error(exc: Exception) -> str | None:
    """Diagnostic FR d'une erreur Graph (code/subcode), ou None si inconnue.

    Le cas 190/460 (session invalidée : mot de passe changé ou révocation
    Facebook) exige une reconnexion manuelle — aucun retry ne le réparera.
    """
    body = ""
    try:
        resp = getattr(exc, "response", None)
        if resp is not None:
            body = resp.text or ""
    except Exception:
        body = ""
    if '"code":190' in body.replace(" ", "") and ("460" in body):
        return (
            "Session Facebook invalidée (code 190/460 : mot de passe changé ou "
            "session révoquée par Facebook). Reconnectez la Page : nouveau "
            "Jeton Page Facebook dans Configuration → Clés sécurisées."
        )
    if '"code":190' in body.replace(" ", ""):
        return (
            "Jeton Facebook rejeté par Meta (code 190). Reconnectez la Page : "
            "nouveau Jeton Page Facebook dans Configuration → Clés sécurisées."
        )
    return None


def _token_status_path():
    from .config import ROOT

    return ROOT / "Logs" / "fb_token_status.json"


def clear_token_status_cache() -> None:
    """À appeler quand l'utilisateur enregistre un nouveau jeton."""
    try:
        _token_status_path().unlink(missing_ok=True)
    except OSError:
        pass


def facebook_token_status(config: dict, token: str | None, max_age_hours: int = 6) -> dict:
    """État vivant du jeton Page (cache 6 h) : {ok, message, checked_at}.

    Ne lève jamais : en cas de panne réseau on renvoie l'ancien cache, sinon
    un état "unknown" (ok=None) pour ne pas crier au loup. C'est ce voyant
    qui évite de découvrir un token mort 2 jours plus tard dans l'Historique.
    """
    path = _token_status_path()
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(cached, dict) and cached.get("checked_at"):
            age = (datetime.now() - datetime.fromisoformat(cached["checked_at"])).total_seconds()
            if age < max_age_hours * 3600:
                return cached
    except Exception:
        cached = None
    if not token:
        return {"ok": False, "message": "absent (aucun jeton)", "checked_at": datetime.now().isoformat()}
    try:
        resp = requests.get(
            f"https://graph.facebook.com/{config['facebook']['api_version']}/{config.get('page_id')}",
            params={"fields": "id,name", "access_token": token},
            timeout=15,
        )
        resp.raise_for_status()
        name = (resp.json() or {}).get("name") or "Page"
        state = {"ok": True, "message": f"connecté ({name})", "checked_at": datetime.now().isoformat()}
    except Exception as exc:
        diag = explain_graph_error(exc)
        if diag is None and cached and cached.get("ok"):
            return cached  # panne réseau probable : on garde l'ancien état
        state = {
            "ok": False,
            "message": diag or f"injoignable ({exc})",
            "checked_at": datetime.now().isoformat(),
        }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return state


class MetaPublisher:
    def __init__(self, config: dict, token: str, logger):
        self.config = config
        self.token = token
        self.logger = logger
        self.base = f"https://graph.facebook.com/{config['facebook']['api_version']}"

    def validate(self) -> dict:
        try:
            response = requests.get(
                f"{self.base}/{self.config['page_id']}",
                params={
                    "fields": "id,name",
                    "access_token": self.token,
                },
                timeout=30,
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            diag = explain_graph_error(exc)
            if diag:
                self.logger.warning("Facebook : %s", diag)
                raise RuntimeError(diag) from exc
            raise
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
                # Tag @followers/@topfans pour notifier les abonnés (2e commentaire), même si le 1er a échoué
                try:
                    tag_resp = requests.post(
                        f"{self.base}/{post_id}/comments",
                        data={"message": "@followers @topfans", "access_token": self.token},
                        timeout=45,
                    )
                    tag_resp.raise_for_status()
                    self.logger.info("Tag @followers @topfans posté sur %s", post_id)
                except requests.RequestException as tag_exc:
                    self.logger.warning("Tag @followers non posté (%s) : %s", post_id, tag_exc)

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