# Streamlit Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Excel output with a Streamlit web dashboard where the team can view social media stats, upload CSVs, and edit post labels.

**Architecture:** Streamlit app backed by SQLite. Reuses existing `csv_import.py` for CSV parsing. Three new files: `database.py` (data layer), `app.py` (Streamlit UI), and tests. Simple password auth via `st.secrets`.

**Tech Stack:** Streamlit, SQLite3 (stdlib), existing csv_import.py, pytest

---

### Task 1: Database Layer — Schema & Insert

**Files:**
- Create: `database.py`
- Create: `tests/test_database.py`

**Step 1: Write failing tests for database init and post insertion**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python3 -m pytest tests/test_database.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'database'`

**Step 3: Implement database.py**

```python
# database.py
"""SQLite database layer voor Prins Social Tracker."""

import sqlite3
from datetime import datetime, timezone

DEFAULT_DB = "social_tracker.db"

def _connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db(db_path: str = DEFAULT_DB):
    """Create tables if they don't exist."""
    conn = _connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            page TEXT NOT NULL,
            post_id TEXT,
            date TEXT NOT NULL,
            type TEXT DEFAULT 'Post',
            text TEXT DEFAULT '',
            reach INTEGER DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            engagement INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0.0,
            theme TEXT DEFAULT '',
            campaign TEXT DEFAULT '',
            source_file TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(platform, page, date, text)
        );

        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            platform TEXT NOT NULL,
            page TEXT DEFAULT '',
            post_count INTEGER DEFAULT 0,
            uploaded_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

def insert_posts(db_path: str, posts: list[dict], platform: str, page: str) -> int:
    """Insert posts, skip duplicates. Returns number of new posts inserted."""
    conn = _connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for p in posts:
        likes = p.get("likes", 0) or 0
        comments = p.get("comments", 0) or 0
        shares = p.get("shares", 0) or 0
        reach = p.get("reach", 0) or 0
        engagement = likes + comments + shares
        er = (engagement / reach * 100) if reach > 0 else 0.0
        try:
            conn.execute("""
                INSERT INTO posts (platform, page, post_id, date, type, text,
                    reach, impressions, likes, comments, shares, clicks,
                    engagement, engagement_rate, source_file, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                platform, page,
                p.get("id", ""),
                p.get("date", ""),
                p.get("type", "Post"),
                p.get("text", ""),
                reach,
                p.get("views", 0) or 0,
                likes, comments, shares,
                p.get("clicks", 0) or 0,
                engagement, round(er, 2),
                p.get("source", ""),
                now,
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            pass  # duplicate, skip
    conn.commit()
    conn.close()
    return inserted

def get_posts(db_path: str = DEFAULT_DB, platform: str | None = None,
              page: str | None = None) -> list[dict]:
    """Retrieve posts, optionally filtered by platform/page."""
    conn = _connect(db_path)
    query = "SELECT * FROM posts WHERE 1=1"
    params: list = []
    if platform:
        query += " AND platform = ?"
        params.append(platform)
    if page:
        query += " AND page = ?"
        params.append(page)
    query += " ORDER BY date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_post_labels(db_path: str, post_id: int, theme: str, campaign: str):
    """Update theme and campaign for a post."""
    conn = _connect(db_path)
    conn.execute(
        "UPDATE posts SET theme = ?, campaign = ? WHERE id = ?",
        (theme, campaign, post_id)
    )
    conn.commit()
    conn.close()

def log_upload(db_path: str, filename: str, platform: str, page: str, post_count: int):
    """Log a CSV upload."""
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO uploads (filename, platform, page, post_count, uploaded_at) VALUES (?, ?, ?, ?, ?)",
        (filename, platform, page, post_count, datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()

def get_uploads(db_path: str = DEFAULT_DB) -> list[dict]:
    """Retrieve upload history."""
    conn = _connect(db_path)
    rows = conn.execute("SELECT * FROM uploads ORDER BY uploaded_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_monthly_stats(db_path: str = DEFAULT_DB, platform: str | None = None) -> list[dict]:
    """Get aggregated monthly stats."""
    conn = _connect(db_path)
    query = """
        SELECT
            platform, page,
            strftime('%%Y-%%m', date) as month,
            COUNT(*) as total_posts,
            SUM(likes) as total_likes,
            SUM(comments) as total_comments,
            SUM(shares) as total_shares,
            SUM(engagement) as total_engagement,
            SUM(reach) as total_reach,
            SUM(impressions) as total_impressions
        FROM posts WHERE 1=1
    """
    params: list = []
    if platform:
        query += " AND platform = ?"
        params.append(platform)
    query += " GROUP BY platform, page, month ORDER BY month DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python3 -m pytest tests/test_database.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add database.py tests/test_database.py
git commit -m "feat: add SQLite database layer with posts, uploads, and deduplication"
```

---

### Task 2: Database Layer — Query & Update Functions

**Files:**
- Modify: `tests/test_database.py`
- Modify: `database.py` (already implemented above, just testing)

**Step 1: Write failing tests for update_post_labels and get_monthly_stats**

Append to `tests/test_database.py`:

```python
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
```

**Step 2: Run tests to verify they pass**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python3 -m pytest tests/test_database.py -v`
Expected: All 6 tests PASS (implementation already done in Task 1)

**Step 3: Commit**

```bash
git add tests/test_database.py
git commit -m "test: add tests for label updates, monthly stats, and upload logging"
```

---

### Task 3: CSV Upload Integration — Connect csv_import to database

**Files:**
- Create: `tests/test_csv_to_db.py`

**Step 1: Write failing test for CSV → database pipeline**

```python
# tests/test_csv_to_db.py
from pathlib import Path
from csv_import import parse_csv_file, detect_platform
from database import init_db, insert_posts, get_posts, log_upload, get_uploads

SAMPLE_DIR = Path(__file__).parent / "sample_data"

def test_csv_to_database_pipeline(tmp_path):
    """Full pipeline: parse CSV → insert into DB → query back."""
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
```

**Step 2: Run tests to verify they pass**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python3 -m pytest tests/test_csv_to_db.py -v`
Expected: All 2 tests PASS

**Step 3: Commit**

```bash
git add tests/test_csv_to_db.py
git commit -m "test: add CSV-to-database integration tests"
```

---

### Task 4: Streamlit App — Page Config, Auth, and Navigation

**Files:**
- Create: `app.py`
- Create: `.streamlit/secrets.toml` (local only, add to .gitignore)
- Modify: `.gitignore` — add `social_tracker.db` and `.streamlit/secrets.toml`
- Modify: `requirements.txt` — add `streamlit`

**Step 1: Update .gitignore**

Add to `.gitignore`:
```
social_tracker.db
.streamlit/secrets.toml
```

**Step 2: Update requirements.txt**

```
python-dotenv
openpyxl
openai
playwright
pytest
streamlit
```

**Step 3: Create secrets.toml for local dev**

```toml
# .streamlit/secrets.toml
password = "prins2026"
```

**Step 4: Create app.py with auth and navigation shell**

```python
# app.py
"""Prins Social Tracker — Streamlit Dashboard."""

import streamlit as st
from database import init_db, DEFAULT_DB

st.set_page_config(
    page_title="Prins Social Tracker",
    page_icon="📊",
    layout="wide",
)

# Init database on startup
init_db()

def check_password() -> bool:
    """Simple password gate."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.title("Prins Social Tracker")
    password = st.text_input("Wachtwoord", type="password")
    if st.button("Inloggen"):
        if password == st.secrets.get("password", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Onjuist wachtwoord")
    return False


def main():
    if not check_password():
        return

    tab_dashboard, tab_facebook, tab_instagram, tab_upload = st.tabs(
        ["Dashboard", "Facebook Posts", "Instagram Posts", "CSV Upload"]
    )

    with tab_dashboard:
        st.header("Dashboard")
        st.info("Dashboard wordt geladen...")  # Placeholder

    with tab_facebook:
        st.header("Facebook Posts")
        st.info("Facebook posts worden geladen...")  # Placeholder

    with tab_instagram:
        st.header("Instagram Posts")
        st.info("Instagram posts worden geladen...")  # Placeholder

    with tab_upload:
        st.header("CSV Upload")
        st.info("Upload functie wordt geladen...")  # Placeholder


if __name__ == "__main__":
    main()
```

**Step 5: Run the app manually to verify it starts**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python3 -m streamlit run app.py --server.headless true &`
Then open browser and verify login page shows. Kill with Ctrl+C.

**Step 6: Commit**

```bash
git add app.py .gitignore requirements.txt
git commit -m "feat: add Streamlit app shell with auth and tab navigation"
```

---

### Task 5: CSV Upload Tab

**Files:**
- Modify: `app.py` — implement CSV upload tab

**Step 1: Replace the CSV Upload tab placeholder in app.py**

Replace the upload tab block with:

```python
    with tab_upload:
        st.header("CSV Upload")
        st.write("Upload CSV-exports uit Meta Business Suite. "
                 "Het platform (Facebook/Instagram) wordt automatisch gedetecteerd.")

        page = st.selectbox("Pagina", ["prins", "edupet"], key="upload_page")

        uploaded_files = st.file_uploader(
            "Kies CSV-bestanden", type=["csv"], accept_multiple_files=True
        )

        if uploaded_files and st.button("Importeren"):
            import tempfile, os
            from csv_import import parse_csv_file, detect_platform
            from database import insert_posts, log_upload

            total_new = 0
            for uf in uploaded_files:
                # Write to temp file (csv_import expects a file path)
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv",
                                                  delete=False) as tmp:
                    tmp.write(uf.getvalue())
                    tmp_path = tmp.name
                try:
                    platform = detect_platform(tmp_path)
                    posts = parse_csv_file(tmp_path)
                    if posts:
                        count = insert_posts(DEFAULT_DB, posts, platform=platform, page=page)
                        log_upload(DEFAULT_DB, uf.name, platform, page, count)
                        total_new += count
                        st.success(f"{uf.name}: {count} nieuwe {platform} posts geimporteerd")
                    else:
                        st.warning(f"{uf.name}: geen posts gevonden")
                finally:
                    os.unlink(tmp_path)

            if total_new > 0:
                st.balloons()

        # Upload history
        from database import get_uploads
        uploads = get_uploads()
        if uploads:
            st.subheader("Upload geschiedenis")
            st.dataframe(
                [{"Bestand": u["filename"], "Platform": u["platform"],
                  "Pagina": u["page"], "Posts": u["post_count"],
                  "Datum": u["uploaded_at"][:16]} for u in uploads],
                use_container_width=True,
            )
```

**Step 2: Test manually — upload a sample CSV via the browser**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python3 -m streamlit run app.py --server.headless true`
Upload `tests/sample_data/prins_fb.csv` via the UI. Verify "3 nieuwe facebook posts geimporteerd" message.

**Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add CSV upload tab with auto-detection and upload history"
```

---

### Task 6: Facebook & Instagram Post Tables (with editable labels)

**Files:**
- Modify: `app.py` — implement Facebook and Instagram tabs

**Step 1: Implement the posts table helper and both tabs**

Add a helper function and replace both tab placeholders:

```python
import pandas as pd
from database import get_posts, update_post_labels

MAAND_NL = {
    1: "Januari", 2: "Februari", 3: "Maart", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Augustus",
    9: "September", 10: "Oktober", 11: "November", 12: "December",
}

def show_posts_table(platform: str):
    """Render an editable posts table for a platform."""
    posts = get_posts(platform=platform)
    if not posts:
        st.info(f"Nog geen {platform} posts. Upload een CSV via de 'CSV Upload' tab.")
        return

    df = pd.DataFrame(posts)

    # Month filter
    df["month_sort"] = pd.to_datetime(df["date"]).dt.to_period("M")
    months = sorted(df["month_sort"].unique(), reverse=True)
    month_labels = ["Alle"] + [str(m) for m in months]
    selected = st.selectbox("Maand", month_labels, key=f"{platform}_month")

    if selected != "Alle":
        df = df[df["month_sort"] == selected]

    # Page filter
    pages = sorted(df["page"].unique())
    if len(pages) > 1:
        selected_page = st.selectbox("Pagina", ["Alle"] + pages, key=f"{platform}_page")
        if selected_page != "Alle":
            df = df[df["page"] == selected_page]

    # Display columns
    display_cols = ["date", "type", "text", "reach", "impressions", "likes",
                    "comments", "shares", "clicks", "engagement",
                    "engagement_rate", "theme", "campaign"]
    col_labels = {
        "date": "Datum", "type": "Type", "text": "Omschrijving",
        "reach": "Bereik", "impressions": "Weergaven", "likes": "Likes",
        "comments": "Reacties", "shares": "Shares", "clicks": "Klikken",
        "engagement": "Engagement", "engagement_rate": "ER%%",
        "theme": "Thema", "campaign": "Campagne",
    }

    display_df = df[["id"] + display_cols].copy()
    display_df = display_df.rename(columns=col_labels)

    # Editable table
    edited = st.data_editor(
        display_df,
        disabled=[c for c in display_df.columns if c not in ("Thema", "Campagne")],
        hide_index=True,
        use_container_width=True,
        key=f"{platform}_editor",
    )

    # Save changes
    if not edited.equals(display_df):
        for _, row in edited.iterrows():
            orig = display_df[display_df["id"] == row["id"]]
            if orig.empty:
                continue
            orig_row = orig.iloc[0]
            if row["Thema"] != orig_row["Thema"] or row["Campagne"] != orig_row["Campagne"]:
                update_post_labels(DEFAULT_DB, int(row["id"]), row["Thema"], row["Campagne"])
        st.success("Labels opgeslagen!")

    # Summary metrics
    st.caption(f"{len(df)} posts | Totaal engagement: {df['engagement'].sum():,} | "
               f"Gem. bereik: {df['reach'].mean():,.0f}")
```

Then in the tabs:

```python
    with tab_facebook:
        st.header("Facebook Posts")
        show_posts_table("facebook")

    with tab_instagram:
        st.header("Instagram Posts")
        show_posts_table("instagram")
```

**Step 2: Test manually — verify posts table shows after uploading sample CSVs**

Run the app, upload all 3 sample CSVs, check that Facebook and Instagram tabs show the data. Edit a Thema cell, verify it saves.

**Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add Facebook and Instagram post tables with editable labels"
```

---

### Task 7: Dashboard Tab — KPIs and Charts

**Files:**
- Modify: `app.py` — implement dashboard tab

**Step 1: Implement the dashboard tab**

Replace the dashboard tab placeholder:

```python
    with tab_dashboard:
        st.header("Dashboard — Prins Social Tracker")

        from database import get_monthly_stats
        stats = get_monthly_stats()
        all_posts = get_posts()

        if not all_posts:
            st.info("Nog geen data. Upload CSV's via de 'CSV Upload' tab.")
        else:
            df_all = pd.DataFrame(all_posts)
            df_all["date_parsed"] = pd.to_datetime(df_all["date"])

            # KPI cards — current month
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            current_month = now.strftime("%Y-%m")
            df_month = df_all[df_all["date_parsed"].dt.strftime("%Y-%m") == current_month]

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Posts deze maand", len(df_month))
            col2.metric("Totaal engagement", f"{df_month['engagement'].sum():,}")
            col3.metric("Gem. bereik", f"{df_month['reach'].mean():,.0f}" if len(df_month) > 0 else "0")
            col4.metric("Totaal posts", len(df_all))

            # Monthly trend chart
            if stats:
                df_stats = pd.DataFrame(stats)
                st.subheader("Engagement per maand")
                chart_data = df_stats.pivot_table(
                    index="month", columns="platform",
                    values="total_engagement", aggfunc="sum"
                ).fillna(0)
                st.bar_chart(chart_data)

                st.subheader("Aantal posts per maand")
                posts_chart = df_stats.pivot_table(
                    index="month", columns="platform",
                    values="total_posts", aggfunc="sum"
                ).fillna(0)
                st.bar_chart(posts_chart)

                st.subheader("Bereik per maand")
                reach_chart = df_stats.pivot_table(
                    index="month", columns="platform",
                    values="total_reach", aggfunc="sum"
                ).fillna(0)
                st.bar_chart(reach_chart)
```

**Step 2: Test manually — verify dashboard shows KPIs and charts after data is loaded**

**Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add dashboard with KPI cards and monthly trend charts"
```

---

### Task 8: Import Existing Excel Data into Database

**Files:**
- Create: `migrate_excel.py` — one-time migration script

**Step 1: Write migration script**

```python
# migrate_excel.py
"""One-time migration: import existing Excel data into SQLite."""

from openpyxl import load_workbook
from database import init_db, insert_posts, log_upload, DEFAULT_DB

EXCEL_FILE = "Social cijfers 2026 PRINS.xlsx"

def migrate():
    init_db()
    wb = load_workbook(EXCEL_FILE, read_only=True)

    # Facebook posts (tab "Facebook cijfers")
    if "Facebook cijfers" in wb.sheetnames:
        ws = wb["Facebook cijfers"]
        fb_posts = []
        for r in range(4, ws.max_row + 1):
            date_val = ws.cell(row=r, column=2).value
            if not date_val:
                continue
            date_str = str(date_val)[:10] if hasattr(date_val, "isoformat") else str(date_val)
            fb_posts.append({
                "date": date_str,
                "type": ws.cell(row=r, column=3).value or "Post",
                "text": ws.cell(row=r, column=4).value or "",
                "views": ws.cell(row=r, column=5).value or 0,
                "reach": ws.cell(row=r, column=6).value or 0,
                "likes": ws.cell(row=r, column=7).value or 0,
                "comments": ws.cell(row=r, column=8).value or 0,
                "shares": ws.cell(row=r, column=9).value or 0,
                "clicks": ws.cell(row=r, column=10).value or 0,
                "source": "excel_migration",
            })
        if fb_posts:
            count = insert_posts(DEFAULT_DB, fb_posts, platform="facebook", page="prins")
            log_upload(DEFAULT_DB, EXCEL_FILE, "facebook", "prins", count)
            print(f"Facebook: {count} posts geimporteerd")

    # Instagram posts (tab "Instagram cijfers")
    if "Instagram cijfers" in wb.sheetnames:
        ws = wb["Instagram cijfers"]
        ig_posts = []
        for r in range(4, ws.max_row + 1):
            date_val = ws.cell(row=r, column=2).value
            if not date_val:
                continue
            date_str = str(date_val)[:10] if hasattr(date_val, "isoformat") else str(date_val)
            ig_posts.append({
                "date": date_str,
                "type": ws.cell(row=r, column=9).value or "Post",
                "text": ws.cell(row=r, column=8).value or "",
                "reach": ws.cell(row=r, column=10).value or 0,
                "views": ws.cell(row=r, column=11).value or 0,
                "likes": ws.cell(row=r, column=12).value or 0,
                "comments": ws.cell(row=r, column=13).value or 0,
                "shares": 0,
                "clicks": 0,
                "source": "excel_migration",
            })
        if ig_posts:
            count = insert_posts(DEFAULT_DB, ig_posts, platform="instagram", page="prins")
            log_upload(DEFAULT_DB, EXCEL_FILE, "instagram", "prins", count)
            print(f"Instagram: {count} posts geimporteerd")

    wb.close()
    print("Migratie voltooid!")

if __name__ == "__main__":
    migrate()
```

**Step 2: Run the migration**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python3 migrate_excel.py`
Expected: Shows count of imported posts.

**Step 3: Commit**

```bash
git add migrate_excel.py
git commit -m "feat: add one-time Excel-to-SQLite migration script"
```

---

### Task 9: Streamlit Cloud Deployment Config

**Files:**
- Modify: `.gitignore` — ensure secrets excluded
- Verify: `requirements.txt` has all deps

**Step 1: Verify requirements.txt is complete**

Ensure it contains: `streamlit`, `python-dotenv`, `openpyxl`, `openai`, `pandas`
(Remove `playwright` and `pytest` — not needed for deployment)

Create a separate `requirements-dev.txt` for dev tools:
```
playwright
pytest
```

**Step 2: Add Streamlit config for deployment**

Create `.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#E8732C"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F5F5F5"
textColor = "#333333"
font = "sans serif"

[server]
maxUploadSize = 50
```

**Step 3: Commit**

```bash
git add requirements.txt requirements-dev.txt .streamlit/config.toml
git commit -m "chore: add Streamlit deployment config and split requirements"
```

**Step 4: Deploy to Streamlit Community Cloud**

1. Push repo to GitHub
2. Go to share.streamlit.io
3. Connect repo, set `app.py` as main file
4. Add secret `password = "prins2026"` in Streamlit Cloud settings
5. Deploy

---

### Task 10: Final Integration Test

**Step 1: Run all tests**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python3 -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Manual smoke test**

1. Start app locally
2. Log in with password
3. Upload all 3 sample CSVs
4. Verify Dashboard shows KPIs and charts
5. Verify Facebook tab shows 5 posts (3 prins + 2 edupet)
6. Verify Instagram tab shows 3 posts
7. Edit a Thema field, refresh, verify it persists
8. Verify upload history shows 3 entries

**Step 3: Final commit if any fixes needed**
