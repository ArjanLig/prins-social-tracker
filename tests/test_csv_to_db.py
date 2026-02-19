# tests/test_csv_to_db.py
from pathlib import Path
from csv_import import parse_csv_file, detect_platform
from database import init_db, insert_posts, get_posts, log_upload, get_uploads

SAMPLE_DIR = Path(__file__).parent / "sample_data"

def test_csv_to_database_pipeline(tmp_path):
    """Full pipeline: parse CSV -> insert into DB -> query back."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    csv_path = SAMPLE_DIR / "prins_fb.csv"
    platform = detect_platform(csv_path)
    posts = parse_csv_file(csv_path)

    assert platform == "facebook"
    count = insert_posts(db_path, posts, platform=platform, page="prins")
    assert count == 3
    log_upload(db_path, csv_path.name, platform, "prins", count)

    # Verify data in DB
    rows = get_posts(db_path, platform="facebook", page="prins")
    assert len(rows) == 3
    assert rows[0]["likes"] == 85  # most recent first (2026-02-10)

    # Verify upload log
    uploads = get_uploads(db_path)
    assert len(uploads) == 1
    assert uploads[0]["filename"] == "prins_fb.csv"

def test_csv_deduplication_across_uploads(tmp_path):
    """Uploading same CSV twice should not create duplicates."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    csv_path = SAMPLE_DIR / "prins_fb.csv"
    posts = parse_csv_file(csv_path)

    insert_posts(db_path, posts, platform="facebook", page="prins")
    count2 = insert_posts(db_path, posts, platform="facebook", page="prins")
    assert count2 == 0  # all duplicates

    rows = get_posts(db_path)
    assert len(rows) == 3  # still 3, not 6
