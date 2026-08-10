from pathlib import Path

from src.content import Content, ContentGenerator
from src.database import HistoryDatabase


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
