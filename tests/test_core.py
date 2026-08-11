from datetime import datetime
from pathlib import Path

from src.content import Content, ContentGenerator
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
    monkeypatch.setattr("src.manual.get_secret", lambda name: None)
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
