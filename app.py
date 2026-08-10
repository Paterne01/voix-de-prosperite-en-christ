from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request

from src.config import ROOT, absolute_path, load_config, save_config
from src.logging_setup import setup_logging
from src.publishers.tiktok import TikTokOAuth, persist_token
from src.secrets import get_secret, secret_status, set_secret
from src.service import PublicationService

app = Flask(__name__)

_YT_TOKEN_PATH = ROOT / "BaseDeDonnées" / "youtube_token.pickle"
_OAUTH = TikTokOAuth()


def _redirect_uri() -> str:
    return f"{request.host_url.rstrip('/')}/callback/"


def service() -> PublicationService:
    config = load_config()
    return PublicationService(config, setup_logging(config))


@app.get("/")
def index():
    config = load_config()
    instance = service()
    from src.config import format_for

    next_slots = [
        {"time": slot, "format": format_for(config, slot)}
        for slot in config["schedule"]
    ]
    return render_template(
        "index.html",
        config=config,
        secrets=secret_status(),
        publications=instance.database.recent(),
        next_slots=next_slots,
        formats=instance.database.list_formats(),
        now=datetime.now().strftime("%d/%m/%Y %H:%M"),
        youtube_configured=_YT_TOKEN_PATH.exists(),
        youtube_enabled=config.get("publishers", {}).get("youtube", False),
        tiktok_connected=bool(get_secret("tiktok_access_token")),
        tiktok_creds=bool(get_secret("tiktok_client_key") and get_secret("tiktok_client_secret")),
    )


def _parse_networks(value: str) -> list[str]:
    return [name.strip() for name in value.split(",") if name.strip()]


def _parse_schedule(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@app.get("/api/formats")
def list_formats():
    return jsonify(formats=service().database.list_formats())


@app.post("/api/formats")
def create_format():
    name = request.form.get("name", "").strip()
    prompt = request.form.get("prompt", "").strip()
    output_type = request.form.get("output_type", "")
    schedule = _parse_schedule(request.form.get("schedule", ""))
    networks = _parse_networks(request.form.get("networks", ""))
    if not name or output_type not in ("short_comment", "image_text"):
        return jsonify(ok=False, error="Nom et type de sortie requis."), 400
    if not schedule:
        return jsonify(ok=False, error="Au moins un horaire HH:MM requis."), 400
    db = service().database
    format_id = db.create_format(name, prompt, schedule, output_type, networks or ["facebook", "youtube", "tiktok"])
    return jsonify(ok=True, id=format_id)


@app.post("/api/formats/<int:format_id>")
def update_format(format_id: int):
    db = service().database
    if not db.get_format(format_id):
        return jsonify(ok=False, error="Format introuvable."), 404
    name = request.form.get("name", "").strip()
    prompt = request.form.get("prompt", "").strip()
    output_type = request.form.get("output_type", "")
    schedule = _parse_schedule(request.form.get("schedule", ""))
    networks = _parse_networks(request.form.get("networks", ""))
    active = request.form.get("active") == "on"
    if not name or output_type not in ("short_comment", "image_text"):
        return jsonify(ok=False, error="Nom et type de sortie requis."), 400
    if not schedule:
        return jsonify(ok=False, error="Au moins un horaire HH:MM requis."), 400
    db.update_format(format_id, name=name, prompt=prompt, schedule=schedule,
                     output_type=output_type, networks=networks, active=active)
    return jsonify(ok=True)


@app.post("/api/formats/<int:format_id>/delete")
def delete_format(format_id: int):
    db = service().database
    if not db.get_format(format_id):
        return jsonify(ok=False, error="Format introuvable."), 404
    db.delete_format(format_id)
    return jsonify(ok=True)


# ── Format C : publication manuelle ────────────────────────────────

@app.post("/api/manual/upload")
def manual_upload():
    from src.manual import kind_of, list_pending, pending_dir

    config = load_config()
    directory = pending_dir(config)
    if "file" not in request.files:
        return jsonify(ok=False, error="Aucun fichier envoyé."), 400
    file = request.files["file"]
    if not file.filename or kind_of(file.filename) is None:
        return jsonify(ok=False, error="Formats acceptés : JPG, PNG, WEBP, MP4, MOV, WEBM."), 400
    safe_name = Path(file.filename).name
    target = directory / safe_name
    counter = 1
    while target.exists():
        target = directory / f"{Path(safe_name).stem}_{counter}{Path(safe_name).suffix}"
        counter += 1
    file.save(target)
    return jsonify(ok=True, files=list_pending(config))


@app.get("/api/manual/list")
def manual_list():
    from src.manual import list_pending

    return jsonify(files=list_pending(load_config()))


@app.post("/api/manual/preview")
def manual_preview():
    from src.manual import generate_caption, kind_of, list_pending, pending_dir

    config = load_config()
    name = request.form.get("filename", "")
    path = pending_dir(config) / name
    if not path.is_file():
        return jsonify(ok=False, error="Fichier introuvable dans le dossier en attente."), 404
    caption = request.form.get("caption", "").strip() or generate_caption(name)
    return jsonify(ok=True, kind=kind_of(name), caption=caption, files=list_pending(config))


@app.post("/api/manual/publish")
def manual_publish():
    from src.manual import delete_pending, kind_of, list_pending, pending_dir

    config = load_config()
    name = request.form.get("filename", "")
    path = pending_dir(config) / name
    if not path.is_file():
        return jsonify(ok=False, error="Fichier introuvable dans le dossier en attente."), 404
    caption = request.form.get("caption", "").strip()
    if not caption:
        return jsonify(ok=False, error="La légende est vide."), 400
    networks = _parse_networks(request.form.get("networks", ""))
    dry_run = request.form.get("dry_run") == "on"
    try:
        result = service().publish_manual(
            media_path=path,
            caption=caption,
            comment=request.form.get("comment", "").strip(),
            scheduled_for=request.form.get("scheduled_for") or None,
            dry_run=dry_run,
            networks=networks or None,
            filename=name,
        )
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 502
    if not dry_run and result.get("status") in ("published", "partial"):
        delete_pending(config, name)
    result["files"] = list_pending(config)
    return jsonify(result)


@app.get("/api/tiktok/auth")
def tiktok_auth():
    """Génère l'URL d'autorisation OAuth PKCE (à ouvrir dans le navigateur)."""
    client_key = get_secret("tiktok_client_key")
    if not client_key:
        return jsonify(ok=False, error="client_key TikTok manquant"), 400
    url, _state = _OAUTH.build_authorize_url(client_key, _redirect_uri())
    return jsonify(ok=True, url=url)


@app.get("/callback/")
def tiktok_callback():
    """Callback OAuth TikTok : échange le code contre des jetons et redirige."""
    log = logging.getLogger("voix")
    client_key = get_secret("tiktok_client_key")
    client_secret = get_secret("tiktok_client_secret")
    code, state = request.args.get("code"), request.args.get("state")
    log.info(
        "Callback TikTok : code=%s state=%s error=%s error_description=%s",
        bool(code), state, request.args.get("error"), request.args.get("error_description"),
    )
    if not code or not state or not client_key or not client_secret:
        log.warning("Callback TikTok incomplet : %s", dict(request.args))
        return redirect("/?tiktok=error")
    try:
        payload = _OAUTH.exchange(client_key, client_secret, code, state, _redirect_uri())
        persist_token(payload)
        return redirect("/?tiktok=connected")
    except Exception as exc:
        log.exception("Échange de code TikTok échoué : %s", exc)
        return redirect("/?tiktok=error")


@app.post("/api/secrets")
def save_secrets():
    for name, value in request.form.items():
        if value.strip():
            set_secret(name, value)
    return jsonify(ok=True)


@app.post("/api/settings")
def save_settings():
    config = load_config()
    schedule = [item.strip() for item in request.form.get("schedule", "").split(",") if item.strip()]
    if len(schedule) != 4 or any(len(item) != 5 or item[2] != ":" for item in schedule):
        return jsonify(ok=False, error="Utilise quatre horaires HH:MM séparés par une virgule."), 400
    config["schedule"] = schedule
    # Recalcule les formats par créneau : 08:00/16:00 → vidéo ; 00:00/12:00 → déclaration.
    config["schedule_formats"] = {
        item: ("declaration" if item in ("00:00", "12:00") else "video")
        for item in schedule
    }
    config["page_id"] = request.form.get("page_id", "").strip()
    config["logo_path"] = request.form.get("logo_path", "").strip()
    config["image_mode"] = request.form.get("image_mode", "local")
    config["cloud_image"]["enabled"] = request.form.get("cloud_enabled") == "on"
    # Planification manuelle (Format C) : créneaux fixes OU intervalle au choix.
    manual = config.setdefault("manual_schedule", {})
    manual["mode"] = request.form.get("manual_mode", "slots")
    manual["slots"] = _parse_schedule(request.form.get("manual_slots", "04:00,20:00")) or ["04:00", "20:00"]
    try:
        manual["interval_hours"] = int(request.form.get("manual_interval", "4") or "4")
    except ValueError:
        manual["interval_hours"] = 4
    manual["start_hour"] = request.form.get("manual_start", "00:00").strip() or "00:00"
    manual["networks"] = _parse_networks(request.form.get("manual_networks", "facebook,youtube,tiktok"))
    config.setdefault("publishers", {"facebook": True, "youtube": False})
    config["publishers"]["facebook"] = request.form.get("publisher_facebook") == "on"
    config["publishers"]["youtube"] = request.form.get("publisher_youtube") == "on"
    config["publishers"].setdefault("tiktok", {"enabled": False, "audited": False})
    config["publishers"]["tiktok"]["enabled"] = request.form.get("publisher_tiktok") == "on"
    save_config(config)
    return jsonify(ok=True)


@app.post("/api/prepare")
def prepare():
    selected = request.form.get("mode") or None
    fmt = request.form.get("format") or "video"
    result = service().publish(
        mode=selected, dry_run=True, format=fmt,
        prompt=request.form.get("prompt") or None,
        networks=_parse_networks(request.form.get("networks", "")),
        format_name=request.form.get("format_name") or None,
    )
    return jsonify(result)


@app.post("/api/publish")
def publish():
    try:
        fmt = request.form.get("format") or "video"
        return jsonify(service().publish(
            mode=request.form.get("mode") or None, format=fmt,
            prompt=request.form.get("prompt") or None,
            networks=_parse_networks(request.form.get("networks", "")),
            format_name=request.form.get("format_name") or None,
        ))
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 502


@app.get("/api/logs")
def logs():
    config = load_config()
    path = absolute_path(config["paths"]["logs"]) / "logs.txt"
    text = path.read_text(encoding="utf-8")[-12_000:] if path.exists() else "Aucun journal pour le moment."
    return jsonify(text=text)


if __name__ == "__main__":
    from src.scheduler_log import log_run

    def _manual_loop() -> None:
        import threading
        import time as _time

        def tick() -> None:
            from src.manual_scheduler import run_manual

            while True:
                try:
                    cfg = load_config()
                    inst = PublicationService(cfg, setup_logging(cfg))
                    run_manual(cfg, inst, setup_logging(cfg))
                except Exception:
                    logging.getLogger("voix").exception("Tour du planificateur manuel échoué")
                _time.sleep(300)

        threading.Thread(target=tick, daemon=True, name="manual-scheduler").start()

    @log_run("app.py (serveur Flask)")
    def _serve() -> None:
        _manual_loop()
        app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)

    _serve()
