from datetime import datetime
from pathlib import Path

from src.content import HOOK_TYPES, Content, ContentGenerator, normalize_hashtags
from src.config import DEFAULT_WEEK_PILLARS, weekday_pillar
from src.content_declarations import DeclarationGenerator
from src.database import HistoryDatabase
from src.manual import generate_youtube_metadata
from src.manual_scheduler import slot_due_now


class _FakeManualDB:
    """Stub de HistoryDatabase pour slot_due_now (marquage des créneaux faits)."""

    def __init__(self, done: set[str] | None = None) -> None:
        self._done = done or set()

    def manual_slot_done(self, day: str, slot: str) -> bool:
        return f"{day}T{slot}" in self._done


def _manual_config() -> dict:
    return {"manual_schedule": {"mode": "slots", "slots": ["04:00", "20:00"]}}


def test_slot_due_now_waits_for_the_hour():
    """Fichiers déposés en pleine journée : AUCUN créneau n'est dû, on attend."""
    assert slot_due_now(_manual_config(), _FakeManualDB(), datetime(2026, 8, 11, 12, 0)) is None
    assert slot_due_now(_manual_config(), _FakeManualDB(), datetime(2026, 8, 11, 4, 40)) is None


def test_slot_due_now_active_only_around_the_hour():
    assert slot_due_now(_manual_config(), _FakeManualDB(), datetime(2026, 8, 11, 3, 58)) == "04:00"
    assert slot_due_now(_manual_config(), _FakeManualDB(), datetime(2026, 8, 11, 4, 5)) == "04:00"
    assert slot_due_now(_manual_config(), _FakeManualDB(), datetime(2026, 8, 11, 20, 0)) == "20:00"


def test_slot_due_now_skips_already_published_slot():
    db = _FakeManualDB({"2026-08-11T04:00"})
    assert slot_due_now(_manual_config(), db, datetime(2026, 8, 11, 4, 5)) is None


def test_generate_youtube_metadata_fallback_without_key(monkeypatch):
    monkeypatch.setattr("src.manual.ordered_providers", lambda config: [])
    meta = generate_youtube_metadata("provision-divine.mp4", "Dieu pourvoit encore aujourd'hui.")
    assert meta["title"]
    assert meta["description"] == "Dieu pourvoit encore aujourd'hui."
    assert isinstance(meta["tags"], list) and meta["tags"]


def test_local_generator_respects_structure(tmp_path):
    db = HistoryDatabase(tmp_path / "history.sqlite3")
    generator = ContentGenerator(db)
    generated = []
    for _ in range(180):
        content = generator._local({field: {getattr(item, field).casefold() for item in generated} for field in ("title", "topic", "verse_reference", "cta", "decor")})
        generated.append(content)
    assert len({item.title for item in generated}) == 180
    assert all(len(item.title.split()) <= 15 for item in generated)
    assert all(item.hashtags for item in generated)
    assert all(len(item.hashtags) == 5 for item in generated)
    assert all(any(tag in item.comment_text for tag in item.hashtags) for item in generated)
    assert all(int(item.title.split()[0]) == len(item.points) for item in generated)


def test_comment_has_required_sections(tmp_path):
    db = HistoryDatabase(tmp_path / "history.sqlite3")
    content = ContentGenerator(db)._local({field: set() for field in ("title", "topic", "verse_reference", "cta", "decor")})
    assert "Chez toi" in content.comment_text
    assert content.hashtags
    assert any(tag in content.comment_text for tag in content.hashtags)


def test_validate_rejects_count_mismatch(tmp_path):
    db = HistoryDatabase(tmp_path / "history.sqlite3")
    generator = ContentGenerator(db)
    content = generator._build_local(1)
    assert int(content.title.split()[0]) == len(content.points) == 4
    content.points = content.points[:3]
    try:
        generator._validate(
            content,
            {field: [] for field in ("title", "topic", "verse_reference", "cta", "decor")},
        )
    except ValueError as exc:
        assert "nombre" in str(exc).casefold()
    else:
        raise AssertionError("Devrait rejeter un nombre de points incohérent avec le titre")


def test_normalize_hashtags_exactly_five_no_duplicates():
    """Tronque à 5, complète à 5 et ne garde aucun doublon."""
    out = normalize_hashtags(["#A", "#B", "#C", "#D", "#E", "#F", "#A"])
    assert len(out) == 5
    assert len(set(tag.casefold() for tag in out)) == 5
    assert all(tag.startswith("#") for tag in out)


def test_normalize_hashtags_pads_when_short():
    out = normalize_hashtags(["#Sagesse"])
    assert len(out) == 5
    assert out[0] == "#Sagesse"


def test_declarations_local_has_exactly_five_hashtags(tmp_path):
    db = HistoryDatabase(tmp_path / "history.sqlite3")
    gen = DeclarationGenerator(db)
    generated = []
    for _ in range(10):
        declaration = gen._local({field: {item.topic.casefold() for item in generated} for field in ("title", "topic")})
        generated.append(declaration)
    assert all(len(item.hashtags) == 5 for item in generated)


def test_weekday_pillar_default_plan():
    """Par défaut, chaque jour a SON pilier des 7 points (plan hebdomadaire)."""
    config = {"content_plan": {"mode": "day_based"}}
    # Lundi 2026-08-10 -> Dignité, Mardi -> Sagesse, ... Dimanche -> Générosité.
    assert weekday_pillar(config, datetime(2026, 8, 10)) == "Dignité"       # lundi
    assert weekday_pillar(config, datetime(2026, 8, 11)) == "Sagesse"       # mardi
    assert weekday_pillar(config, datetime(2026, 8, 12)) == "Libération"    # mercredi
    assert weekday_pillar(config, datetime(2026, 8, 13)) == "Productivité"  # jeudi
    assert weekday_pillar(config, datetime(2026, 8, 14)) == "Restauration relationnelle"
    assert weekday_pillar(config, datetime(2026, 8, 15)) == "Provision Active"
    assert weekday_pillar(config, datetime(2026, 8, 16)) == "Générosité"    # dimanche


def test_weekday_pillar_random_mode_and_custom_week():
    """mode=random renvoie None ; un plan personnalisé est respecté."""
    assert weekday_pillar({"content_plan": {"mode": "random"}}, datetime(2026, 8, 10)) is None
    custom = {"content_plan": {"mode": "day_based", "week": {"monday": "Sagesse", "tuesday": "Dignité"}}}
    assert weekday_pillar(custom, datetime(2026, 8, 10)) == "Sagesse"
    # Jour non couvert par le plan personnalisé -> repli aléatoire (None via défaut absent).
    assert weekday_pillar(custom, datetime(2026, 8, 12)) in DEFAULT_WEEK_PILLARS.values()


def test_weekday_pillar_defaults_to_today():
    config = {"content_plan": {"mode": "day_based"}}
    assert weekday_pillar(config) in DEFAULT_WEEK_PILLARS.values()


def test_local_generator_honors_forced_pillar(tmp_path):
    db = HistoryDatabase(tmp_path / "history.sqlite3")
    content = ContentGenerator(db)._local(
        {field: set() for field in ("title", "topic", "verse_reference", "cta", "decor")},
        pillar="Sagesse",
    )
    assert content.pillar == "Sagesse"
    assert content.topic.startswith("Sagesse")


def test_declarations_local_honors_forced_pillar(tmp_path):
    db = HistoryDatabase(tmp_path / "history.sqlite3")
    declaration = DeclarationGenerator(db)._local(
        {field: set() for field in ("title", "topic")},
        pillar="Provision Active",
    )
    assert declaration.pillar == "Provision Active"
    assert declaration.topic.startswith("Provision Active")


def test_pick_hook_type_avoids_last_used(tmp_path):
    db = HistoryDatabase(tmp_path / "history.sqlite3")
    generator = ContentGenerator(db)
    seen = set()
    for key, _ in HOOK_TYPES:
        chosen = generator._pick_hook_type()[0]
        assert chosen not in seen
        seen.add(chosen)
        db.create({
            "created_at": datetime.now().isoformat(),
            "pillar": "Dignité", "title": f"t{len(seen)}", "topic": f"topic-{key}",
            "verse_reference": "Proverbes 1:1", "cta": "cta", "decor": "decor",
            "image_prompt": "prompt", "caption": "caption", "comment_text": "comment",
            "hashtags": "#A #B #C #D #E", "hook_type": chosen, "status": "published",
        })


def test_overlay_duration_parses_json_or_default():
    from src.service import _overlay_duration
    assert _overlay_duration(None) == 3
    assert _overlay_duration("") == 3
    assert _overlay_duration('{"duration": 5}') == 5
    assert _overlay_duration('{"duration": 2}', default=3) == 2
    assert _overlay_duration("pas du json", default=2) == 2
    assert _overlay_duration('{"x": 1}', default=2) == 2


def test_is_image_and_video_file_detection():
    from pathlib import Path
    from src.video import _is_image_file, _is_video_file
    assert _is_image_file(Path("a.PNG"))
    assert _is_image_file(Path("a.jpg"))
    assert _is_image_file(Path("a.jpeg"))
    assert _is_image_file(Path("a.webp"))
    assert not _is_image_file(Path("a.mp4"))
    assert _is_video_file(Path("a.MP4"))
    assert _is_video_file(Path("a.mov"))
    assert _is_video_file(Path("a.webm"))
    assert _is_video_file(Path("a.avi"))
    assert not _is_video_file(Path("a.png"))


def test_image_intro_outro_converted_and_cleaned(tmp_path):
    """Une intro/outro IMAGE devient un clip vidéo ; les fichiers tmp sont purgés."""
    import json
    import subprocess
    from PIL import Image
    from src.video import build_short_video, _probe_duration, _has_audio

    main = tmp_path / "main.jpg"
    Image.new("RGB", (1080, 1920), (18, 42, 70)).save(main)
    audio = tmp_path / "audio.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
         "-af", "volume=0.3", "-c:a", "aac", str(audio)],
        check=True, capture_output=True,
    )
    intro = tmp_path / "intro.png"
    Image.new("RGB", (500, 900), (200, 30, 30)).save(intro)
    outro = tmp_path / "outro.jpg"
    Image.new("RGB", (300, 600), (30, 200, 30)).save(outro)

    out = build_short_video(
        main, audio, output_dir=tmp_path, max_duration=10,
        intro_path=intro, outro_path=outro,
        intro_duration=3, outro_duration=4,
    )
    assert out.exists() and out.stat().st_size > 10_000
    assert _probe_duration(out) <= 10.5
    assert _has_audio(out)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith("tmp_")]
    assert not leftovers, f"clips temporaires non purgés : {leftovers}"
