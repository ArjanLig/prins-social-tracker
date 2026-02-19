# tests/test_database.py
import sqlite3
from database import init_db, insert_posts, get_posts, update_post_labels, get_monthly_stats

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

def test_update_post_labels(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    posts = [
        {"date": "2026-02-10T14:30:00", "type": "Foto", "text": "Test",
         "reach": 100, "views": 200, "likes": 10, "comments": 2,
         "shares": 1, "clicks": 5, "source": "test.csv"},
    ]
    insert_posts(str(db_path), posts, platform="facebook", page="prins")
    rows = get_posts(str(db_path))
    update_post_labels(str(db_path), rows[0]["id"], "Puppies", "Voorjaar 2026")
    rows = get_posts(str(db_path))
    assert rows[0]["theme"] == "Puppies"
    assert rows[0]["campaign"] == "Voorjaar 2026"

def test_get_monthly_stats(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    posts = [
        {"date": "2026-02-10T14:30:00", "type": "Foto", "text": "Post 1",
         "reach": 100, "views": 200, "likes": 10, "comments": 2,
         "shares": 1, "clicks": 5, "source": "t.csv"},
        {"date": "2026-02-15T10:00:00", "type": "Video", "text": "Post 2",
         "reach": 200, "views": 400, "likes": 20, "comments": 4,
         "shares": 2, "clicks": 10, "source": "t.csv"},
    ]
    insert_posts(str(db_path), posts, platform="facebook", page="prins")
    stats = get_monthly_stats(str(db_path))
    assert len(stats) == 1
    assert stats[0]["month"] == "2026-02"
    assert stats[0]["total_posts"] == 2
    assert stats[0]["total_likes"] == 30

def test_log_and_get_uploads(tmp_path):
    from database import log_upload, get_uploads
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    log_upload(str(db_path), "test.csv", "facebook", "prins", 5)
    uploads = get_uploads(str(db_path))
    assert len(uploads) == 1
    assert uploads[0]["filename"] == "test.csv"
    assert uploads[0]["post_count"] == 5
