from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request

from src.config import ROOT, absolute_path, load_config, save_config
from src.logging_setup import setup_logging
from src.publishers.tiktok import TikTokOAuth, persist_token
from src.scheduler import PostScheduler
from src.secrets import get_secret, secret_status, set_secret
from src.service import PublicationService

app = Flask(__name__)
# Les templates sont relus à chaque requête : une édition d'interface est
# visible immédiatement sans redémarrer le serveur.
app.config["TEMPLATES_AUTO_RELOAD"] = True

_YT_TOKEN_PATH = ROOT / "BaseDeDonnées" / "youtube_token.pickle"
_OAUTH = TikTokOAuth()

_scheduler_instance: PostScheduler | None = None


def _redirect_uri() -> str:
    return f"{request.host_url.rstrip('/')}/callback/"


def service() -> PublicationService:
    config = load_config()
    return PublicationService(config, setup_logging(config))


def get_scheduler() -> PostScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        config = load_config()
        _scheduler_instance = PostScheduler(config, setup_logging(config))
        _scheduler_instance.start(config)
    return _scheduler_instance


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


def _networks_from_request() -> list[str]:
    """Réseaux cochés dans le formulaire (checkboxes facebook/youtube/tiktok).

    Gère à la fois les checkboxes multiples (getlist) et l'ancien champ texte
    comma-separated pour rétrocompatibilité.
    """
    # Checkboxes : plusieurs valeurs avec même nom "networks"
    lst = request.form.getlist("networks")
    if lst:
        # getlist peut retourner ["facebook,youtube"] si l'ancien champ texte est encore là
        out: list[str] = []
        for item in lst:
            out.extend(_parse_networks(item))
        # dédoublonne en gardant l'ordre
        seen: set[str] = set()
        uniq: list[str] = []
        for n in out:
            low = n.lower()
            if low not in seen:
                seen.add(low)
                uniq.append(low)
        return uniq
    return _parse_networks(request.form.get("networks", ""))


def _manual_networks_from_request() -> list[str]:
    lst = request.form.getlist("manual_networks")
    if lst:
        out: list[str] = []
        for item in lst:
            out.extend(_parse_networks(item))
        seen: set[str] = set()
        uniq: list[str] = []
        for n in out:
            low = n.lower()
            if low not in seen:
                seen.add(low)
                uniq.append(low)
        return uniq
    return _parse_networks(request.form.get("manual_networks", "facebook,youtube,tiktok"))


def _parse_schedule(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@app.post("/api/config/tts")
def config_tts():
    config = load_config()
    enabled = request.form.get("enabled") == "on" or request.form.get("enabled") == "true" or request.json and request.json.get("enabled")
    # Support both form and JSON
    if request.is_json:
        enabled = bool(request.json.get("enabled"))
    else:
        enabled = request.form.get("enabled") in ("on", "true", "1")
    config["tts_enabled"] = bool(enabled)
    if request.form.get("voice") or (request.is_json and request.json.get("voice")):
        config["tts_voice"] = request.form.get("voice") or request.json.get("voice")
    save_config(config)
    return jsonify(ok=True, tts_enabled=config["tts_enabled"])


@app.get("/api/formats")
def list_formats():
    return jsonify(formats=service().database.list_formats())


# ── Overlays (intro/outro vidéo, watermark, texte image) ─────────────

@app.get("/overlays")
def overlays_page():
    db = service().database
    return render_template(
        "overlays.html",
        overlays=db.list_overlays(),
        types=db.OVERLAY_TYPES,
        now=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )


@app.get("/api/overlays")
def list_overlays():
    db = service().database
    return jsonify(overlays=db.list_overlays())


@app.post("/api/overlays")
def create_overlay():
    from src.config import absolute_path

    db = service().database
    params = _overlay_params()
    if not params["name"] or params["overlay_type"] not in db.OVERLAY_TYPES:
        return jsonify(ok=False, error="Nom et type d'overlay requis."), 400
    overlay_type = params["overlay_type"]
    if overlay_type in ("intro", "outro", "watermark"):
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify(ok=False, error=f"Un fichier vidéo est requis pour un overlay « {overlay_type} »."), 400
        ext = Path(file.filename).suffix.lower()
        allowed = _overlay_allowed_extensions(overlay_type)
        if ext not in allowed:
            return jsonify(
                ok=False,
                error=f"Type « {ext or 'inconnu'} » refusé pour un overlay « {overlay_type} ». "
                      f"Formats acceptés : {', '.join(sorted(allowed))}.",
            ), 400
        target = _save_overlay_file(file)
        params["file_path"] = str(target)
        # Intro/outro IMAGE : on mémorise la durée d'affichage via text_content.
        if overlay_type in ("intro", "outro") and ext in _OVERLAY_IMAGE_EXTS:
            params["text_content"] = json.dumps({"duration": _overlay_duration_from_form()})
    elif overlay_type == "image_text" and not params["text_content"]:
        return jsonify(ok=False, error="Le texte de la banderole est requis."), 400
    overlay_id = db.create_overlay(**params)
    return jsonify(ok=True, id=overlay_id, overlays=db.list_overlays())


@app.post("/api/overlays/<int:overlay_id>")
def update_overlay(overlay_id: int):
    db = service().database
    record = db.get_overlay(overlay_id)
    if not record:
        return jsonify(ok=False, error="Overlay introuvable."), 404
    params = _overlay_params(record)
    if not params["name"] or params["overlay_type"] not in db.OVERLAY_TYPES:
        return jsonify(ok=False, error="Nom et type d'overlay requis."), 400
    overlay_type = params["overlay_type"]
    if overlay_type in ("intro", "outro", "watermark"):
        file = request.files.get("file")
        if file and file.filename:
            ext = Path(file.filename).suffix.lower()
            allowed = _overlay_allowed_extensions(overlay_type)
            if ext not in allowed:
                return jsonify(
                    ok=False,
                    error=f"Type « {ext or 'inconnu'} » refusé pour un overlay « {overlay_type} ». "
                          f"Formats acceptés : {', '.join(sorted(allowed))}.",
                ), 400
            params["file_path"] = str(_save_overlay_file(file))
            if overlay_type in ("intro", "outro") and ext in _OVERLAY_IMAGE_EXTS:
                params["text_content"] = json.dumps({"duration": _overlay_duration_from_form()})
    elif overlay_type == "image_text" and not params["text_content"]:
        return jsonify(ok=False, error="Le texte de la banderole est requis."), 400
    db.update_overlay(overlay_id, **params)
    return jsonify(ok=True, overlays=db.list_overlays())


@app.post("/api/overlays/<int:overlay_id>/toggle")
def toggle_overlay(overlay_id: int):
    db = service().database
    record = db.get_overlay(overlay_id)
    if not record:
        return jsonify(ok=False, error="Overlay introuvable."), 404
    active = request.form.get("active") == "on"
    db.set_overlay_active(overlay_id, active)
    return jsonify(ok=True, overlays=db.list_overlays())


@app.post("/api/overlays/<int:overlay_id>/delete")
def delete_overlay(overlay_id: int):
    db = service().database
    if not db.get_overlay(overlay_id):
        return jsonify(ok=False, error="Overlay introuvable."), 404
    db.delete_overlay(overlay_id)
    return jsonify(ok=True, overlays=db.list_overlays())


def _overlay_params(defaults: dict | None = None) -> dict:
    """Construit les paramètres d'overlay depuis le formulaire.

    Pour la création : `active` prend la valeur de la case à cocher (absente
    quand décochée). Pour la modification : on part des valeurs enregistrées et
    on ne garde que les champs réellement envoyés.
    """
    if defaults is None:
        active = request.form.get("active") == "on"
    else:
        value = request.form.get("active")
        active = value == "on" if value is not None else bool(defaults.get("active"))
    return {
        "name": (request.form.get("name") or (defaults or {}).get("name") or "").strip(),
        "overlay_type": request.form.get("overlay_type") or (defaults or {}).get("overlay_type") or "",
        "file_path": None,
        "text_content": request.form.get("text_content") or (defaults or {}).get("text_content"),
        "active": active,
        "format_scope": request.form.get("format_scope") or (defaults or {}).get("format_scope") or "all",
    }


def _overlay_dir() -> Path:
    from src.config import ROOT as _ROOT

    root = _ROOT / "assets" / "overlays"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _save_overlay_file(file) -> Path:
    safe_name = Path(file.filename).name
    target = _overlay_dir() / f"{datetime.now():%Y%m%d_%H%M%S}_{safe_name}"
    file.save(target)
    return target


# Intro/outro acceptent vidéos ET images (une image est convertie en clip fixe).
_OVERLAY_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_OVERLAY_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".avi"}
# Watermark : vidéo OU image (fond transparent conseillé).
_OVERLAY_WATERMARK_EXTS = _OVERLAY_VIDEO_EXTS | _OVERLAY_IMAGE_EXTS


def _overlay_allowed_extensions(overlay_type: str) -> set[str]:
    if overlay_type in ("intro", "outro"):
        return _OVERLAY_VIDEO_EXTS | _OVERLAY_IMAGE_EXTS
    if overlay_type == "watermark":
        return _OVERLAY_WATERMARK_EXTS
    return set()


def _overlay_duration_from_form() -> int:
    """Durée d'affichage choisie dans le formulaire (2/3/4/5 s, défaut 3)."""
    try:
        value = int(request.form.get("duration", "3"))
    except (TypeError, ValueError):
        return 3
    return value if value in (2, 3, 4, 5) else 3


@app.post("/api/formats")
def create_format():
    name = request.form.get("name", "").strip()
    prompt = request.form.get("prompt", "").strip()
    output_type = request.form.get("output_type", "")
    schedule = _parse_schedule(request.form.get("schedule", ""))
    networks = _networks_from_request()
    if not name or output_type not in ("short_comment", "image_text"):
        return jsonify(ok=False, error="Nom et type de sortie requis."), 400
    if not schedule:
        return jsonify(ok=False, error="Au moins un horaire HH:MM requis."), 400
    db = service().database
    format_id = db.create_format(name, prompt, schedule, output_type, networks or ["facebook", "youtube", "tiktok"])
    get_scheduler().sync(load_config())
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
    networks = _networks_from_request()
    active = request.form.get("active") == "on"
    if not name or output_type not in ("short_comment", "image_text"):
        return jsonify(ok=False, error="Nom et type de sortie requis."), 400
    if not schedule:
        return jsonify(ok=False, error="Au moins un horaire HH:MM requis."), 400
    db.update_format(format_id, name=name, prompt=prompt, schedule=schedule,
                     output_type=output_type, networks=networks, active=active)
    get_scheduler().sync(load_config())
    return jsonify(ok=True)


@app.post("/api/formats/<int:format_id>/delete")
def delete_format(format_id: int):
    db = service().database
    if not db.get_format(format_id):
        return jsonify(ok=False, error="Format introuvable."), 404
    db.delete_format(format_id)
    get_scheduler().sync(load_config())
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
    manual["networks"] = _manual_networks_from_request() or ["facebook", "youtube", "tiktok"]
    config.setdefault("publishers", {"facebook": True, "youtube": False})
    config["publishers"]["facebook"] = request.form.get("publisher_facebook") == "on"
    config["publishers"]["youtube"] = request.form.get("publisher_youtube") == "on"
    config["publishers"].setdefault("tiktok", {"enabled": False, "audited": False})
    config["publishers"]["tiktok"]["enabled"] = request.form.get("publisher_tiktok") == "on"
    save_config(config)
    get_scheduler().sync(config)
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


# ── Anti-shadowban : stats du jour ─────────────────────────────────────

@app.get("/api/today-stats")
def today_stats():
    config = load_config()
    db = service().database
    limit = int(config.get("max_posts_per_day", 3))
    stats = db.today_stats(limit)
    windows = config.get("schedule_windows") or []
    # Prochaine fenêtre : la première non encore passée aujourd'hui
    from datetime import datetime as _dt
    now_min = _dt.now().hour * 60 + _dt.now().minute
    next_win = None
    for w in windows:
        try:
            _, end_s = w.split("-")
            eh, em = map(int, end_s.strip().split(":"))
            if eh * 60 + em >= now_min:
                next_win = w
                break
        except Exception:
            continue
    if not next_win and windows:
        next_win = windows[0]
    return jsonify(posts_today=stats["posts_today"], limit=limit, next_window=next_win or "08:00")


# ── Planification (APScheduler) ─────────────────────────────────────

@app.get("/api/scheduler")
def scheduler_status():
    config = load_config()
    return jsonify(
        running=get_scheduler().scheduler.running,
        timezone=config.get("timezone", "Africa/Nairobi"),
        jobs=get_scheduler().scheduled_jobs(),
    )


@app.post("/api/scheduler/sync")
def scheduler_sync():
    get_scheduler().sync(load_config())
    return jsonify(ok=True, jobs=get_scheduler().scheduled_jobs())


@app.post("/api/catch-up")
def catch_up():
    from src.jobs import run_catch_up

    config = load_config()
    dry_run = request.form.get("dry_run") == "on"
    try:
        result = run_catch_up(config, service(), dry_run=dry_run)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 502
    return jsonify(result)


@app.get("/batch-status")
def batch_status():
    from src.config import absolute_path
    import sqlite3
    db_path = absolute_path(load_config()["paths"]["database"])
    try:
        conn = sqlite3.connect(str(db_path))
        cnt = conn.execute("SELECT COUNT(*) FROM content_queue WHERE status='pending'").fetchone()[0]
        nxt = conn.execute("SELECT scheduled_for FROM content_queue WHERE status='pending' ORDER BY scheduled_for LIMIT 1").fetchone()
        conn.close()
        return jsonify(queue_count=cnt, next_scheduled=nxt[0] if nxt else None, week_generated=cnt>0)
    except Exception as e:
        return jsonify(queue_count=0, next_scheduled=None, week_generated=False, error=str(e))


@app.get("/dashboard")
def dashboard():
    import sqlite3
    from src.config import absolute_path
    db_path = str(absolute_path(load_config()["paths"]["database"]))
    conn = sqlite3.connect(db_path)
    try:
        total_posts = conn.execute("SELECT COUNT(*) FROM publications WHERE status IN ('published','partial')").fetchone()[0]
        # Vues/likes : post_genome si rempli, sinon 0 (affichage fallback)
        avg_views = conn.execute("SELECT AVG(views_24h) FROM post_genome WHERE views_24h > 0").fetchone()[0]
        if not avg_views:
            avg_views = conn.execute("SELECT AVG(views_total) FROM publications WHERE views_total > 0").fetchone()[0] or 0
        avg_likes = conn.execute("SELECT AVG(likes_24h) FROM post_genome WHERE likes_24h > 0").fetchone()[0]
        if not avg_likes:
            avg_likes = conn.execute("SELECT AVG(likes_total) FROM publications WHERE likes_total > 0").fetchone()[0] or 0
        top_angles = conn.execute("SELECT pillar, angle_type, strength_score, usage_count FROM viral_angles ORDER BY strength_score DESC LIMIT 5").fetchall()
        # Top posts : d'abord par vues, fallback sur les plus récents (même sans vues)
        top_posts = conn.execute("SELECT pillar, angle_type, views_24h, likes_24h, shares_24h, platform FROM post_genome WHERE views_24h > 0 ORDER BY views_24h DESC LIMIT 3").fetchall()
        if not top_posts:
            top_posts = conn.execute("SELECT pillar, hook_type, 0, 0, 0, platform FROM post_genome ORDER BY post_id DESC LIMIT 3").fetchall()
        if not top_posts:
            # Fallback ultime : publications récentes
            rows = conn.execute("SELECT pillar, title, 0, 0, 0, format FROM publications WHERE status IN ('published','partial') ORDER BY id DESC LIMIT 3").fetchall()
            top_posts = [(r[0], (r[1][:20] if r[1] else r[5]), 0, 0, 0, r[5]) for r in rows]
        queue_count = conn.execute("SELECT COUNT(*) FROM content_queue WHERE status='pending'").fetchone()[0]
        pending_manual = conn.execute("SELECT COUNT(*) FROM publications WHERE format='manual' AND status IN ('published','partial') AND substr(created_at,1,10)=date('now')").fetchone()[0]
        best_hour = conn.execute("SELECT publish_hour, AVG(views_24h) as avg_v FROM post_genome WHERE views_24h > 0 GROUP BY publish_hour ORDER BY avg_v DESC LIMIT 1").fetchone()
        if not best_hour:
            best_hour = conn.execute("SELECT CAST(substr(scheduled_for,12,2) AS INTEGER) as h, COUNT(*) as c FROM publications WHERE scheduled_for IS NOT NULL GROUP BY h ORDER BY c DESC LIMIT 1").fetchone()
            if best_hour:
                best_hour = (best_hour[0], best_hour[1])
        best_emotion = None
        try:
            best_emotion = conn.execute("SELECT emotion, AVG(pg.views_24h) FROM post_genome pg JOIN viral_angles va ON va.angle_type=pg.angle_type WHERE pg.views_24h > 0 GROUP BY va.emotion ORDER BY 2 DESC LIMIT 1").fetchone()
            if not best_emotion or not best_emotion[0]:
                best_emotion = conn.execute("SELECT pillar, COUNT(*) FROM publications GROUP BY pillar ORDER BY 2 DESC LIMIT 1").fetchone()
        except Exception:
            pass
        conn.close()
        return render_template('dashboard.html',
            total_posts=total_posts, avg_views=round(avg_views or 0), avg_likes=round(avg_likes or 0),
            top_angles=top_angles, top_posts=top_posts, queue_count=queue_count,
            best_hour=best_hour, best_emotion=best_emotion, pending_manual=pending_manual)
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return f"Dashboard error: {e}", 500


@app.post("/batch/generate-week")
def batch_generate_week():
    from src.batch_generator import generate_week_batch
    from src.config import absolute_path
    config = load_config()
    db_path = str(absolute_path(config["paths"]["database"]))
    try:
        n = generate_week_batch(db_path)
        return jsonify(ok=True, generated=n)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500


@app.get("/recycler/candidates")
def recycler_candidates():
    from src.recycler import find_recyclable
    from src.config import absolute_path
    config = load_config()
    db_path = str(absolute_path(config["paths"]["database"]))
    try:
        rows = find_recyclable(db_path, min_views=30)
        # Format as list of dicts
        out = []
        for r in rows:
            out.append({"id": r[0], "title": r[4] if len(r) > 4 else "", "views": r[7] if len(r) > 7 else 0, "likes": r[8] if len(r) > 8 else 0})
        return jsonify(candidates=out)
    except Exception as exc:
        return jsonify(candidates=[], error=str(exc))


@app.post("/recycler/run")
def recycler_run():
    from src.recycler import run_recycling
    from src.config import absolute_path
    config = load_config()
    db_path = str(absolute_path(config["paths"]["database"]))
    try:
        n = run_recycling(db_path)
        return jsonify(ok=True, recycled=n)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500


@app.post("/learning/run")
def learning_run():
    from src.learning import run_learning_cycle
    from src.config import absolute_path
    config = load_config()
    db_path = str(absolute_path(config["paths"]["database"]))
    try:
        run_learning_cycle(db_path)
        return jsonify(ok=True)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 500


# ── Panneau de contrôle : reprise / annulation ──────────────────────

@app.get("/api/pending")
def pending_list():
    return jsonify(publications=service().database.pending())


@app.post("/api/publications/<int:publication_id>/resume")
def resume_publication(publication_id: int):
    from src.manual import kind_of

    config = load_config()
    file = request.files.get("file")
    image_path = None
    if file and file.filename:
        if kind_of(file.filename) != "image":
            return jsonify(ok=False, error="Seule une image est acceptée (JPG, PNG, WEBP)."), 400
        safe_name = Path(file.filename).name
        target = absolute_path(config["paths"].get("images", "Images")) / f"resume_{publication_id}_{safe_name}"
        file.save(target)
        image_path = str(target)
    networks = _parse_networks(request.form.get("networks", ""))
    dry_run = request.form.get("dry_run") == "on"
    try:
        result = service().resume(
            publication_id=publication_id, image_path=image_path,
            networks=networks or None, dry_run=dry_run,
        )
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 502
    return jsonify(result)


@app.post("/api/publications/<int:publication_id>/cancel")
def cancel_publication(publication_id: int):
    db = service().database
    if not db.get(publication_id):
        return jsonify(ok=False, error="Publication introuvable."), 404
    db.cancel(publication_id)
    return jsonify(ok=True)


# ── Rattrapage Facebook seul ─────────────────────────────────────────
# Republie UNIQUEMENT sur Facebook les publications du jour qui ont manqué
# Facebook (jeton invalide au moment du post). YouTube/TikTok ne sont pas
# re-contactés : aucun doublon. Sans publication_id, cible automatiquement
# toutes les publications du jour manquantes côté Facebook.

@app.post("/api/republish-facebook")
def republish_facebook():
    dry_run = request.form.get("dry_run") == "on" or request.args.get("dry_run") == "1"
    try:
        result = service().republish_facebook(dry_run=dry_run)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 502
    return jsonify(result)


@app.post("/api/publications/<int:publication_id>/republish-facebook")
def republish_facebook_one(publication_id: int):
    dry_run = request.form.get("dry_run") == "on" or request.args.get("dry_run") == "1"
    try:
        result = service().republish_facebook(publication_id, dry_run=dry_run)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 502
    return jsonify(result)


if __name__ == "__main__":
    from src.console import configure_console
    from src.scheduler_log import log_run

    @log_run("app.py (serveur Flask)")
    def _serve() -> None:
        configure_console()
        # Initialise les angles viraux si vide
        try:
            from src.angle_engine import init_angles
            from src.config import absolute_path
            cfg = load_config()
            init_angles(str(absolute_path(cfg.get("paths", {}).get("database", "BaseDeDonnées/voix_prosperite.sqlite3"))))
        except Exception:
            pass
        # Démarre APScheduler : créneaux des formats actifs + boucle manuelle.
        get_scheduler()
        app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)

    _serve()
