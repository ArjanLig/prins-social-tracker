# tests/test_database.py
import sqlite3
from database import init_db, insert_posts, get_posts

def test_init_db_creates_tables(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    conn = sqlite3.connect(str(db_path))
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert "posts" in tables
    assert "uploads" in tables

def test_insert_posts_and_retrieve(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    posts = [
        {"date": "2026-02-10T14:30:00", "type": "Foto", "text": "Test post",
         "reach": 1200, "views": 3400, "likes": 85, "comments": 12,
         "shares": 8, "clicks": 45, "source": "test.csv"},
    ]
    count = insert_posts(str(db_path), posts, platform="facebook", page="prins")
    assert count == 1
    rows = get_posts(str(db_path))
    assert len(rows) == 1
    assert rows[0]["text"] == "Test post"
    assert rows[0]["platform"] == "facebook"
    assert rows[0]["page"] == "prins"
    assert rows[0]["likes"] == 85

def test_insert_posts_deduplicates(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    posts = [
        {"date": "2026-02-10T14:30:00", "type": "Foto", "text": "Test post",
         "reach": 1200, "views": 3400, "likes": 85, "comments": 12,
         "shares": 8, "clicks": 45, "source": "test.csv"},
    ]
    insert_posts(str(db_path), posts, platform="facebook", page="prins")
    insert_posts(str(db_path), posts, platform="facebook", page="prins")
    rows = get_posts(str(db_path))
    assert len(rows) == 1
