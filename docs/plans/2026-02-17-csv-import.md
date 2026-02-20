# CSV Import Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** CSV-bestanden uit Meta Business Suite importeren als primaire databron voor Facebook en Instagram posts.

**Architecture:** Nieuw `csv_import.py` module met flexibele kolommapping en auto-detectie van platform/pagina. `fetch_stats.py` krijgt een `--csv` argument. CSV-data wordt genormaliseerd naar hetzelfde dict-formaat dat de scraper en API al gebruiken, zodat de bestaande `write_fb_posts`/`write_ig_posts` functies ongewijzigd werken.

**Tech Stack:** Python csv (stdlib), bestaande openpyxl pipeline

---

### Task 1: csv_import.py — kolommapping en parsing

**Files:**
- Create: `csv_import.py`
- Create: `tests/test_csv_import.py`
- Create: `tests/sample_data/prins_fb.csv`
- Create: `tests/sample_data/edupet_fb.csv`
- Create: `tests/sample_data/prins_ig.csv`

**Step 1: Maak sample CSV's aan**

Maak een `tests/sample_data/` map met drie kleine CSV-bestanden die het Meta Business Suite formaat nabootsen.

`tests/sample_data/prins_fb.csv`:
```csv
Publicatietijdstip,Berichttype,Titel,Bereik,Weergaven,Reacties,Opmerkingen,Deelacties,Totaal aantal klikken
2026-02-10 14:30,Foto,Nieuwe Prins lijn!,1200,3400,85,12,8,45
2026-02-05 09:15,Video,Puppy voedingstips,2500,8900,120,25,15,78
2026-01-20 16:00,Link,Blog over kattenvoer,800,2100,40,5,3,22
```

`tests/sample_data/edupet_fb.csv`:
```csv
Publicatietijdstip,Berichttype,Titel,Bereik,Weergaven,Reacties,Opmerkingen,Deelacties,Totaal aantal klikken
2026-02-12 10:00,Foto,Edupet training event,600,1800,30,8,4,15
2026-01-28 13:45,Video,Honden gedragstips,1100,4200,55,14,9,33
```

`tests/sample_data/prins_ig.csv`:
```csv
Publicatietijdstip,Media type,Titel,Bereik,Weergaven,Vind-ik-leuks,Opmerkingen
2026-02-11 12:00,IMAGE,Prins hondenbrokken,950,2800,110,18
2026-02-03 17:30,CAROUSEL_ALBUM,Kattenlijn fotoshoot,1400,4100,165,22
2026-01-15 10:45,REELS,Behind the scenes,3200,9500,280,45
```

**Step 2: Schrijf tests voor `parse_csv_file`**

`tests/test_csv_import.py`:
```python
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
```

Run: `cd /Users/administrator/Documents/github/prins-social-tracker && python3 -m pytest tests/test_csv_import.py -v`
Expected: FAIL (csv_import module bestaat nog niet)

**Step 3: Implementeer `csv_import.py`**

```python
"""CSV import module voor Meta Business Suite exports."""

import csv
from datetime import datetime
from pathlib import Path

# Flexibele kolommapping: intern veld → mogelijke CSV-kolomnamen
COLUMN_MAP = {
    "datum": ["Publicatietijdstip", "Datum", "Date", "Created", "Aangemaakt"],
    "type": ["Berichttype", "Type", "Media type", "Post Type", "Content type"],
    "tekst": ["Titel", "Bericht", "Caption", "Message", "Beschrijving", "Post Message"],
    "bereik": ["Bereik", "Reach", "Lifetime Post Total Reach"],
    "weergaven": ["Weergaven", "Impressions", "Views", "Lifetime Post Total Impressions"],
    "likes": ["Reacties", "Likes", "Vind-ik-leuks", "Lifetime Post Like Reactions"],
    "reacties": ["Opmerkingen", "Comments", "Lifetime Post Comments"],
    "shares": ["Deelacties", "Shares", "Lifetime Post Shares"],
    "klikken": ["Totaal aantal klikken", "Clicks", "Link Clicks",
                "Lifetime Post Total Clicks"],
}

# Kolommen die alleen in Instagram voorkomen
IG_ONLY_COLUMNS = {"Vind-ik-leuks", "Media type"}
# Kolommen die alleen in Facebook voorkomen
FB_ONLY_COLUMNS = {"Deelacties", "Berichttype", "Totaal aantal klikken"}


def _resolve_columns(header: list[str]) -> dict[str, str | None]:
    """Match CSV-kolomnamen naar interne veldnamen."""
    mapping = {}
    header_lower = {h: h for h in header}
    for field, candidates in COLUMN_MAP.items():
        mapping[field] = None
        for candidate in candidates:
            for h in header:
                if h.strip().lower() == candidate.lower():
                    mapping[field] = h
                    break
            if mapping[field]:
                break
    return mapping


def _parse_date(value: str) -> str:
    """Parseer datum-string naar ISO-formaat."""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M",
                "%d/%m/%Y %H:%M", "%Y-%m-%d", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt).isoformat()
        except ValueError:
            continue
    return value.strip()


def _safe_int(value) -> int:
    """Converteer waarde naar int, 0 bij lege/ongeldige waarden."""
    if not value or value == "":
        return 0
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (ValueError, TypeError):
        return 0


def detect_platform(csv_path: str | Path) -> str:
    """Detecteer of een CSV Facebook of Instagram data bevat."""
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
    header_set = {h.strip() for h in header}
    if header_set & IG_ONLY_COLUMNS:
        return "instagram"
    if header_set & FB_ONLY_COLUMNS:
        return "facebook"
    # Fallback: check bestandsnaam
    name = Path(csv_path).stem.lower()
    if "ig" in name or "instagram" in name or "insta" in name:
        return "instagram"
    return "facebook"


def parse_csv_file(csv_path: str | Path) -> list[dict]:
    """Parseer een Meta Business Suite CSV naar een lijst van post-dicts."""
    posts = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        col_map = _resolve_columns(reader.fieldnames or [])

        for row in reader:
            date_col = col_map.get("datum")
            if not date_col or not row.get(date_col, "").strip():
                continue

            post = {
                "date": _parse_date(row[date_col]),
                "type": (row.get(col_map["type"] or "", "") or "").strip() or "Post",
                "text": (row.get(col_map["tekst"] or "", "") or "").strip(),
                "reach": _safe_int(row.get(col_map["bereik"] or "")),
                "views": _safe_int(row.get(col_map["weergaven"] or "")),
                "likes": _safe_int(row.get(col_map["likes"] or "")),
                "comments": _safe_int(row.get(col_map["reacties"] or "")),
                "shares": _safe_int(row.get(col_map["shares"] or "")),
                "clicks": _safe_int(row.get(col_map["klikken"] or "")),
                "source": str(Path(csv_path).name),
            }
            posts.append(post)
    return posts


def parse_csv_folder(folder_path: str) -> dict[str, list[dict]]:
    """Scan een map op CSV-bestanden en groepeer per platform.

    Returns:
        {"facebook": [{"file": "naam.csv", "posts": [...]}, ...],
         "instagram": [{"file": "naam.csv", "posts": [...]}, ...]}
    """
    folder = Path(folder_path)
    result = {"facebook": [], "instagram": []}
    for csv_file in sorted(folder.glob("*.csv")):
        platform = detect_platform(csv_file)
        posts = parse_csv_file(csv_file)
        if posts:
            result[platform].append({"file": csv_file.name, "posts": posts})
            print(f"  {csv_file.name}: {len(posts)} {platform} posts")
    return result
```

**Step 4: Run tests**

Run: `cd /Users/administrator/Documents/github/prins-social-tracker && python3 -m pytest tests/test_csv_import.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add csv_import.py tests/
git commit -m "feat: voeg csv_import module toe met auto-detectie en flexibele kolommapping"
```

---

### Task 2: Integreer CSV-import in fetch_stats.py

**Files:**
- Modify: `fetch_stats.py` (main functie + argparse)

**Step 1: Voeg `--csv` argument toe aan argparse**

In `fetch_stats.py`, wijzig de `main()` functie. Voeg toe na de bestaande `--no-analysis` argument:

```python
parser.add_argument("--csv", metavar="MAP",
                    help="Map met CSV exports uit Meta Business Suite")
```

**Step 2: Voeg CSV-import flow toe aan main()**

Na het laden van de workbook en voor de scraper-sectie, voeg CSV-import toe:

```python
    # ── CSV Import (primair) ──
    prins_fb_posts = []
    edupet_fb_posts = []
    ig_posts = []

    if args.csv:
        from csv_import import parse_csv_folder
        print(f"\nCSV import uit: {args.csv}")
        csv_data = parse_csv_folder(args.csv)

        for fb_file in csv_data["facebook"]:
            name = fb_file["file"].lower()
            if "edupet" in name:
                edupet_fb_posts = fb_file["posts"]
                print(f"  → Edupet FB: {len(edupet_fb_posts)} posts uit {fb_file['file']}")
            else:
                prins_fb_posts = fb_file["posts"]
                print(f"  → Prins FB: {len(prins_fb_posts)} posts uit {fb_file['file']}")

        for ig_file in csv_data["instagram"]:
            ig_posts = ig_file["posts"]
            print(f"  → Prins IG: {len(ig_posts)} posts uit {ig_file['file']}")
```

Verplaats de bestaande scraper-sectie naar een `else` blok (of laat hem aanvullend draaien als er geen CSV is).

**Step 3: Maak env variabelen optioneel als CSV wordt gebruikt**

Als `--csv` wordt meegegeven, moeten API-tokens niet meer verplicht zijn:

```python
    if not args.csv:
        missing = [k for k, v in required.items() if not v]
        if missing:
            print("Ontbrekende environment variabelen:")
            for key in missing:
                print(f"  - {key}")
            raise SystemExit(1)
```

**Step 4: Pas write_fb_posts aan voor CSV-data met bereik/klikken**

De CSV bevat `reach` en `clicks` die de scraper niet had. Voeg toe in de post-schrijf-loop:

```python
        bereik = post.get("reach", 0)
        if bereik:
            ws.cell(row=row, column=6, value=bereik)             # F: Bereik
        klikken = post.get("clicks", 0)
        if klikken:
            ws.cell(row=row, column=10, value=klikken)           # J: Klikken
```

**Step 5: Pas write_ig_posts aan voor CSV-data**

Instagram posts uit CSV gebruiken een ander dict-formaat dan API posts. Normaliseer het formaat zodat `write_ig_posts` beide aankan. Voeg boven de schrijf-loop een normalisatiestap toe:

```python
    for post in posts:
        # Normaliseer CSV-formaat naar API-formaat
        if "timestamp" not in post and "date" in post:
            post["timestamp"] = post["date"]
        if "like_count" not in post and "likes" in post:
            post["like_count"] = post["likes"]
        if "comments_count" not in post and "comments" in post:
            post["comments_count"] = post["comments"]
        if "media_type" not in post and "type" in post:
            post["media_type"] = post["type"]
        if "caption" not in post and "text" in post:
            post["caption"] = post["text"]
        if "reach" not in post:
            post["reach"] = 0
        if "impressions" not in post and "views" in post:
            post["impressions"] = post["views"]
```

**Step 6: Test handmatig met sample data**

Run: `cd /Users/administrator/Documents/github/prins-social-tracker && python3 fetch_stats.py --csv tests/sample_data --no-analysis`
Expected: Posts uit sample CSV's worden naar Excel geschreven

**Step 7: Commit**

```bash
git add fetch_stats.py
git commit -m "feat: integreer CSV-import in fetch_stats als primaire databron"
```

---

### Task 3: Scraper als aanvulling op CSV-data

**Files:**
- Modify: `fetch_stats.py` (main functie)

**Step 1: Laat scraper ontbrekende velden aanvullen**

Na de CSV-import en scraper secties, voeg merge-logica toe. Als CSV-posts geen engagement data hebben maar de scraper wel, vul aan:

```python
def merge_scraper_data(csv_posts: list[dict], scraper_posts: list[dict]) -> list[dict]:
    """Vul CSV-posts aan met scraper-data waar velden ontbreken."""
    # Index scraper posts op datum (YYYY-MM-DD)
    scraper_by_date = {}
    for p in scraper_posts:
        date_key = p.get("date", "")[:10]
        if date_key:
            scraper_by_date.setdefault(date_key, []).append(p)

    for post in csv_posts:
        date_key = post.get("date", "")[:10]
        matches = scraper_by_date.get(date_key, [])
        if not matches:
            continue
        # Gebruik eerste match op dezelfde dag
        sp = matches[0]
        for field in ("likes", "comments", "shares", "views"):
            if not post.get(field) and sp.get(field):
                post[field] = sp[field]
    return csv_posts
```

**Step 2: Roep merge aan in main() als zowel CSV als scraper data beschikbaar is**

```python
    # Scraper aanvullen als CSV primair is
    if args.csv and has_fb_session():
        print("\nScraper: aanvullen ontbrekende data...")
        result = scrape_fb_page_posts("PrinsPetfoods", max_posts=25, max_scrolls=10)
        scraper_posts = result.get("posts", [])
        if scraper_posts and prins_fb_posts:
            prins_fb_posts = merge_scraper_data(prins_fb_posts, scraper_posts)
            print(f"  ✓ {len(scraper_posts)} scraper posts gemerged")
```

**Step 3: Test**

Run: `cd /Users/administrator/Documents/github/prins-social-tracker && python3 fetch_stats.py --csv tests/sample_data --no-analysis`
Expected: CSV-data + scraper aanvulling

**Step 4: Commit**

```bash
git add fetch_stats.py
git commit -m "feat: scraper vult ontbrekende CSV-data aan via merge"
```

---

### Task 4: Update requirements en documentatie

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`

**Step 1: Voeg pytest toe aan requirements**

```
pytest
```

**Step 2: Update README met CSV-instructies**

Voeg een sectie toe over het gebruik van CSV-import:

```markdown
## CSV Import

1. Exporteer je posts vanuit Meta Business Suite als CSV
2. Zet alle CSV-bestanden in één map
3. Draai het script met: `python3 fetch_stats.py --csv /pad/naar/csv-map/`

Het script herkent automatisch of een CSV Facebook of Instagram data bevat.
Zet "edupet" in de bestandsnaam voor Edupet-data (bijv. `edupet_fb.csv`).
```

**Step 3: Commit en push**

```bash
git add requirements.txt README.md
git commit -m "docs: update README met CSV-import instructies"
git push
```
