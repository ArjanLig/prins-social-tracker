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
        CREATE TABLE IF NOT EXISTS follower_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            page TEXT NOT NULL,
            month TEXT NOT NULL,
            followers INTEGER NOT NULL,
            recorded_at TEXT NOT NULL,
            UNIQUE(platform, page, month)
        );
    """)
    conn.commit()
    conn.close()


def save_follower_snapshot(db_path: str, platform: str, page: str,
                           followers: int, month: str | None = None) -> None:
    """Sla het aantal volgers op voor een specifieke maand (default: huidige maand)."""
    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect(db_path)
    conn.execute("""
        INSERT INTO follower_snapshots (platform, page, month, followers, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(platform, page, month) DO UPDATE SET
            followers = excluded.followers,
            recorded_at = excluded.recorded_at
    """, (platform, page, month, followers, now))
    conn.commit()
    conn.close()


def get_follower_previous_month(db_path: str, platform: str,
                                 page: str) -> int | None:
    """Haal het aantal volgers van vorige maand op."""
    now = datetime.now(timezone.utc)
    if now.month == 1:
        prev_month = f"{now.year - 1}-12"
    else:
        prev_month = f"{now.year}-{now.month - 1:02d}"
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT followers FROM follower_snapshots WHERE platform = ? AND page = ? AND month = ?",
        (platform, page, prev_month),
    ).fetchone()
    conn.close()
    return row["followers"] if row else None


def insert_posts(db_path: str, posts: list[dict], platform: str,
                  page: str | None = None) -> int:
    """Insert posts, skip duplicates. Returns number of new posts inserted.

    Als een post een 'page' veld heeft wordt dat gebruikt, anders de
    meegegeven page parameter. Posts zonder page worden overgeslagen.
    """
    conn = _connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    # Cache follower counts voor engagement rate berekening
    _follower_cache: dict[tuple, int] = {}
    inserted = 0
    for p in posts:
        if not p.get("date"):
            continue
        post_page = p.get("page") or page
        if not post_page:
            continue  # onbekend account, overslaan
        likes = p.get("likes", 0) or 0
        comments = p.get("comments", 0) or 0
        shares = p.get("shares", 0) or 0
        reach = p.get("reach", 0) or 0
        engagement = likes + comments + shares
        # Engagement rate op basis van volgers
        post_month = p.get("date", "")[:7]
        cache_key = (platform, post_page, post_month)
        if cache_key not in _follower_cache:
            row = conn.execute(
                "SELECT followers FROM follower_snapshots "
                "WHERE platform = ? AND page = ? AND month = ?",
                cache_key,
            ).fetchone()
            _follower_cache[cache_key] = row["followers"] if row else 0
        followers = _follower_cache[cache_key]
        er = (engagement / followers * 100) if followers > 0 else 0.0
        try:
            conn.execute("""
                INSERT INTO posts (platform, page, post_id, date, type, text,
                    reach, impressions, likes, comments, shares, clicks,
                    engagement, engagement_rate, source_file, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                platform, post_page,
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
            # Update reach/impressions if they were 0
            views = p.get("views", 0) or 0
            if reach > 0 or views > 0:
                conn.execute("""
                    UPDATE posts SET reach = ?, impressions = ?
                    WHERE platform = ? AND page = ? AND date = ? AND text = ?
                    AND reach = 0 AND impressions = 0
                """, (reach, views, platform, post_page,
                      p.get("date", ""), p.get("text", "")))
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
            strftime('%Y-%m', date) as month,
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
