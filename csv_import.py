"""CSV import module voor Meta Business Suite exports."""

import csv
from datetime import datetime
from pathlib import Path

# Flexibele kolommapping: intern veld -> mogelijke CSV-kolomnamen
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
    result: dict[str, list[dict]] = {"facebook": [], "instagram": []}
    for csv_file in sorted(folder.glob("*.csv")):
        platform = detect_platform(csv_file)
        posts = parse_csv_file(csv_file)
        if posts:
            result[platform].append({"file": csv_file.name, "posts": posts})
            print(f"  {csv_file.name}: {len(posts)} {platform} posts")
    return result
