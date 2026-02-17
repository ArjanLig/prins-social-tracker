import os
from pathlib import Path
from csv_import import parse_csv_file, detect_platform, parse_csv_folder

SAMPLE_DIR = Path(__file__).parent / "sample_data"


def test_parse_fb_csv():
    posts = parse_csv_file(SAMPLE_DIR / "prins_fb.csv")
    assert len(posts) == 3
    assert posts[0]["text"] == "Nieuwe Prins lijn!"
    assert posts[0]["date"] == "2026-02-10T14:30:00"
    assert posts[0]["type"] == "Foto"
    assert posts[0]["reach"] == 1200
    assert posts[0]["views"] == 3400
    assert posts[0]["likes"] == 85
    assert posts[0]["comments"] == 12
    assert posts[0]["shares"] == 8
    assert posts[0]["clicks"] == 45


def test_parse_ig_csv():
    posts = parse_csv_file(SAMPLE_DIR / "prins_ig.csv")
    assert len(posts) == 3
    assert posts[0]["likes"] == 110
    assert posts[0]["type"] == "IMAGE"
    # IG heeft geen shares/clicks
    assert posts[0]["shares"] == 0
    assert posts[0]["clicks"] == 0


def test_detect_platform_fb():
    assert detect_platform(SAMPLE_DIR / "prins_fb.csv") == "facebook"


def test_detect_platform_ig():
    assert detect_platform(SAMPLE_DIR / "prins_ig.csv") == "instagram"


def test_parse_csv_folder():
    result = parse_csv_folder(str(SAMPLE_DIR))
    assert "facebook" in result
    assert "instagram" in result
    # 2 FB csv's = prins + edupet
    assert len(result["facebook"]) == 2
    assert len(result["instagram"]) == 1
    # Check totaal posts
    total_fb = sum(len(f["posts"]) for f in result["facebook"])
    assert total_fb == 5
