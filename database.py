# database.py
"""Database layer voor Prins Social Tracker — Turso (libSQL) + lokale SQLite fallback."""

import json
import os
import sqlite3
from datetime import datetime, timezone

import requests
import streamlit as st

DEFAULT_DB = "social_tracker.db"


def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.getenv(key, default)


TURSO_URL = _get_secret("TURSO_DATABASE_URL")
TURSO_TOKEN = _get_secret("TURSO_AUTH_TOKEN")
_USE_TURSO = bool(TURSO_URL and TURSO_TOKEN)


# ── Turso HTTP API ──

def _turso_execute(sql: str, params: list | None = None) -> list[dict]:
    """Execute a query via Turso HTTP API. Returns list of row dicts."""
    url = TURSO_URL.replace("libsql://", "https://")
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json",
    }
    stmt = {"type": "execute", "stmt": {"sql": sql}}
    if params:
        stmt["stmt"]["args"] = [
            {"type": "null", "value": None} if v is None
            else {"type": "integer", "value": str(v)} if isinstance(v, int)
            else {"type": "float", "value": v} if isinstance(v, float)
            else {"type": "text", "value": str(v)}
            for v in params
        ]
    body = {"requests": [stmt, {"type": "close"}]}
    resp = requests.post(f"{url}/v3/pipeline", json=body, headers=headers, timeout=15)
    resp.raise_for_status()
    result = resp.json()

    # Parse response
    res = result.get("results", [{}])[0].get("response", {}).get("result", {})
    cols = [c["name"] for c in res.get("cols", [])]
    rows = []
    for row in res.get("rows", []):
        rows.append({cols[i]: cell.get("value") for i, cell in enumerate(row)})
    return rows


def _turso_batch(statements: list[tuple[str, list]]) -> None:
    """Execute multiple statements in a batch."""
    url = TURSO_URL.replace("libsql://", "https://")
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json",
    }
    reqs = []
    for sql, params in statements:
        stmt = {"type": "execute", "stmt": {"sql": sql}}
        if params:
            stmt["stmt"]["args"] = [
                {"type": "null", "value": None} if v is None
                else {"type": "integer", "value": str(v)} if isinstance(v, int)
                else {"type": "float", "value": v} if isinstance(v, float)
                else {"type": "text", "value": str(v)}
                for v in params
            ]
        reqs.append(stmt)
    reqs.append({"type": "close"})
    body = {"requests": reqs}
    resp = requests.post(f"{url}/v3/pipeline", json=body, headers=headers, timeout=30)
    resp.raise_for_status()


# ── Local SQLite fallback ──

def _connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Public API ──

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL, page TEXT NOT NULL, post_id TEXT,
        date TEXT NOT NULL, type TEXT DEFAULT 'Post', text TEXT DEFAULT '',
        reach INTEGER DEFAULT 0, impressions INTEGER DEFAULT 0,
        likes INTEGER DEFAULT 0, comments INTEGER DEFAULT 0,
        shares INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0,
        engagement INTEGER DEFAULT 0, engagement_rate REAL DEFAULT 0.0,
        theme TEXT DEFAULT '', campaign TEXT DEFAULT '',
        source_file TEXT DEFAULT '', created_at TEXT NOT NULL,
        UNIQUE(platform, page, date, text)
    )""",
    """CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL, platform TEXT NOT NULL,
        page TEXT DEFAULT '', post_count INTEGER DEFAULT 0,
        uploaded_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS follower_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL, page TEXT NOT NULL,
        month TEXT NOT NULL, followers INTEGER NOT NULL,
        recorded_at TEXT NOT NULL,
        UNIQUE(platform, page, month)
    )""",
    """CREATE TABLE IF NOT EXISTS remarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT DEFAULT 'open',
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS ai_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month TEXT NOT NULL,
        platform TEXT DEFAULT 'cross',
        page TEXT DEFAULT '',
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(month, platform, page)
    )""",
]


def init_db(db_path: str = DEFAULT_DB):
    if _USE_TURSO:
        for sql in _SCHEMA:
            try:
                _turso_execute(sql)
            except Exception:
                pass
    else:
        conn = _connect(db_path)
        for sql in _SCHEMA:
            conn.execute(sql)
        conn.commit()
        conn.close()


def save_follower_snapshot(db_path: str, platform: str, page: str,
                           followers: int, month: str | None = None) -> None:
    if month is None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
    now = datetime.now(timezone.utc).isoformat()
    sql = """INSERT INTO follower_snapshots (platform, page, month, followers, recorded_at)
             VALUES (?, ?, ?, ?, ?)
             ON CONFLICT(platform, page, month) DO UPDATE SET
                 followers = excluded.followers, recorded_at = excluded.recorded_at"""
    params = [platform, page, month, followers, now]
    if _USE_TURSO:
        _turso_execute(sql, params)
    else:
        conn = _connect(db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()
    get_follower_count.clear()
    get_follower_previous_month.clear()


@st.cache_data(ttl=300)
def get_follower_count(db_path: str, platform: str, page: str, month: str) -> int | None:
    sql = "SELECT followers FROM follower_snapshots WHERE platform = ? AND page = ? AND month = ?"
    params = [platform, page, month]
    if _USE_TURSO:
        rows = _turso_execute(sql, params)
        return int(rows[0]["followers"]) if rows else None
    else:
        conn = _connect(db_path)
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row["followers"] if row else None


@st.cache_data(ttl=300)
def get_follower_previous_month(db_path: str, platform: str, page: str) -> int | None:
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    sql = ("SELECT followers FROM follower_snapshots "
           "WHERE platform = ? AND page = ? AND month < ? "
           "ORDER BY month DESC LIMIT 1")
    params = [platform, page, current_month]
    if _USE_TURSO:
        rows = _turso_execute(sql, params)
        return int(rows[0]["followers"]) if rows else None
    else:
        conn = _connect(db_path)
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row["followers"] if row else None


def insert_posts(db_path: str, posts: list[dict], platform: str,
                  page: str | None = None) -> int:
    now = datetime.now(timezone.utc).isoformat()
    inserted = 0

    if _USE_TURSO:
        # Get follower cache
        _follower_cache: dict[tuple, int] = {}
        for p in posts:
            if not p.get("date"):
                continue
            post_page = p.get("page") or page
            if not post_page:
                continue
            likes = p.get("likes", 0) or 0
            comments = p.get("comments", 0) or 0
            shares = p.get("shares", 0) or 0
            reach = p.get("reach", 0) or 0
            engagement = likes + comments + shares
            post_month = p.get("date", "")[:7]
            cache_key = (platform, post_page, post_month)
            if cache_key not in _follower_cache:
                rows = _turso_execute(
                    "SELECT followers FROM follower_snapshots WHERE platform = ? AND page = ? AND month = ?",
                    list(cache_key))
                _follower_cache[cache_key] = int(rows[0]["followers"]) if rows else 0
            followers = _follower_cache[cache_key]
            er = (engagement / followers * 100) if followers > 0 else 0.0
            views = p.get("views", 0) or 0
            try:
                _turso_execute(
                    """INSERT INTO posts (platform,page,post_id,date,type,text,
                        reach,impressions,likes,comments,shares,clicks,
                        engagement,engagement_rate,source_file,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [platform, post_page, p.get("id", ""), p.get("date", ""),
                     p.get("type", "Post"), p.get("text", ""), reach, views,
                     likes, comments, shares, p.get("clicks", 0) or 0,
                     engagement, round(er, 2), p.get("source", ""), now])
                inserted += 1
            except Exception:
                # Update if exists
                updates = []
                params = []
                if reach > 0:
                    updates.append("reach = ?")
                    params.append(reach)
                if views > 0:
                    updates.append("impressions = ?")
                    params.append(views)
                if updates:
                    params.extend([platform, post_page, p.get("date", ""), p.get("text", "")])
                    _turso_execute(
                        f"UPDATE posts SET {', '.join(updates)} WHERE platform = ? AND page = ? AND date = ? AND text = ?",
                        params)
    else:
        conn = _connect(db_path)
        _follower_cache = {}
        for p in posts:
            if not p.get("date"):
                continue
            post_page = p.get("page") or page
            if not post_page:
                continue
            likes = p.get("likes", 0) or 0
            comments = p.get("comments", 0) or 0
            shares = p.get("shares", 0) or 0
            reach = p.get("reach", 0) or 0
            engagement = likes + comments + shares
            post_month = p.get("date", "")[:7]
            cache_key = (platform, post_page, post_month)
            if cache_key not in _follower_cache:
                row = conn.execute(
                    "SELECT followers FROM follower_snapshots WHERE platform = ? AND page = ? AND month = ?",
                    cache_key).fetchone()
                _follower_cache[cache_key] = row["followers"] if row else 0
            followers = _follower_cache[cache_key]
            er = (engagement / followers * 100) if followers > 0 else 0.0
            try:
                conn.execute(
                    """INSERT INTO posts (platform,page,post_id,date,type,text,
                        reach,impressions,likes,comments,shares,clicks,
                        engagement,engagement_rate,source_file,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (platform, post_page, p.get("id", ""), p.get("date", ""),
                     p.get("type", "Post"), p.get("text", ""), reach,
                     p.get("views", 0) or 0, likes, comments, shares,
                     p.get("clicks", 0) or 0, engagement, round(er, 2),
                     p.get("source", ""), now))
                inserted += 1
            except sqlite3.IntegrityError:
                views = p.get("views", 0) or 0
                updates = []
                params = []
                if reach > 0:
                    updates.append("reach = ?")
                    params.append(reach)
                if views > 0:
                    updates.append("impressions = ?")
                    params.append(views)
                if updates:
                    params.extend([platform, post_page, p.get("date", ""), p.get("text", "")])
                    conn.execute(
                        f"UPDATE posts SET {', '.join(updates)} WHERE platform = ? AND page = ? AND date = ? AND text = ?",
                        params)
        conn.commit()
        conn.close()
    get_posts.clear()
    get_monthly_stats.clear()
    return inserted


@st.cache_data(ttl=300)
def get_posts(db_path: str = DEFAULT_DB, platform: str | None = None,
              page: str | None = None) -> list[dict]:
    sql = "SELECT * FROM posts WHERE 1=1"
    params = []
    if platform:
        sql += " AND platform = ?"
        params.append(platform)
    if page:
        sql += " AND page = ?"
        params.append(page)
    sql += " ORDER BY date DESC"
    if _USE_TURSO:
        rows = _turso_execute(sql, params)
        # Convert numeric strings back to ints/floats
        for row in rows:
            for key in ("reach", "impressions", "likes", "comments", "shares",
                        "clicks", "engagement", "id"):
                if key in row and row[key] is not None:
                    try:
                        row[key] = int(row[key])
                    except (ValueError, TypeError):
                        pass
            if "engagement_rate" in row and row["engagement_rate"] is not None:
                try:
                    row["engagement_rate"] = float(row["engagement_rate"])
                except (ValueError, TypeError):
                    pass
        return rows
    else:
        conn = _connect(db_path)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def update_post_labels(db_path: str, post_id: int, theme: str, campaign: str):
    sql = "UPDATE posts SET theme = ?, campaign = ? WHERE id = ?"
    params = [theme, campaign, post_id]
    if _USE_TURSO:
        _turso_execute(sql, params)
    else:
        conn = _connect(db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()


def log_upload(db_path: str, filename: str, platform: str, page: str, post_count: int):
    sql = "INSERT INTO uploads (filename, platform, page, post_count, uploaded_at) VALUES (?, ?, ?, ?, ?)"
    params = [filename, platform, page, post_count, datetime.now(timezone.utc).isoformat()]
    if _USE_TURSO:
        _turso_execute(sql, params)
    else:
        conn = _connect(db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()


def get_uploads(db_path: str = DEFAULT_DB) -> list[dict]:
    sql = "SELECT * FROM uploads ORDER BY uploaded_at DESC"
    if _USE_TURSO:
        return _turso_execute(sql)
    else:
        conn = _connect(db_path)
        rows = conn.execute(sql).fetchall()
        conn.close()
        return [dict(r) for r in rows]


@st.cache_data(ttl=300)
def get_monthly_stats(db_path: str = DEFAULT_DB, platform: str | None = None) -> list[dict]:
    sql = """SELECT platform, page,
                strftime('%Y-%m', date) as month,
                COUNT(*) as total_posts,
                SUM(likes) as total_likes,
                SUM(comments) as total_comments,
                SUM(shares) as total_shares,
                SUM(engagement) as total_engagement,
                SUM(reach) as total_reach,
                SUM(impressions) as total_impressions
            FROM posts WHERE 1=1"""
    params = []
    if platform:
        sql += " AND platform = ?"
        params.append(platform)
    sql += " GROUP BY platform, page, month ORDER BY month DESC"
    if _USE_TURSO:
        rows = _turso_execute(sql, params if params else None)
        for row in rows:
            for key in ("total_posts", "total_likes", "total_comments", "total_shares",
                        "total_engagement", "total_reach", "total_impressions"):
                if key in row and row[key] is not None:
                    try:
                        row[key] = int(row[key])
                    except (ValueError, TypeError):
                        pass
        return rows
    else:
        conn = _connect(db_path)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def add_remark(db_path: str, author: str, message: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    sql = "INSERT INTO remarks (author, message, created_at) VALUES (?, ?, ?)"
    params = [author, message, now]
    if _USE_TURSO:
        _turso_execute(sql, params)
    else:
        conn = _connect(db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()


def get_remarks(db_path: str = DEFAULT_DB) -> list[dict]:
    sql = "SELECT * FROM remarks ORDER BY created_at DESC"
    if _USE_TURSO:
        rows = _turso_execute(sql)
        for row in rows:
            if "id" in row and row["id"] is not None:
                row["id"] = int(row["id"])
        return rows
    else:
        conn = _connect(db_path)
        rows = conn.execute(sql).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def update_remark_status(db_path: str, remark_id: int, status: str) -> None:
    sql = "UPDATE remarks SET status = ? WHERE id = ?"
    params = [status, remark_id]
    if _USE_TURSO:
        _turso_execute(sql, params)
    else:
        conn = _connect(db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()


def save_report(db_path: str, month: str, content: str,
                platform: str = "cross", page: str = "") -> None:
    now = datetime.now(timezone.utc).isoformat()
    sql = """INSERT INTO ai_reports (month, platform, page, content, created_at)
             VALUES (?, ?, ?, ?, ?)
             ON CONFLICT(month, platform, page) DO UPDATE SET
                 content = excluded.content, created_at = excluded.created_at"""
    params = [month, platform, page, content, now]
    if _USE_TURSO:
        _turso_execute(sql, params)
    else:
        conn = _connect(db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()


def get_report(db_path: str, month: str, platform: str = "cross",
               page: str = "") -> str | None:
    sql = "SELECT content FROM ai_reports WHERE month = ? AND platform = ? AND page = ?"
    params = [month, platform, page]
    if _USE_TURSO:
        rows = _turso_execute(sql, params)
        return rows[0]["content"] if rows else None
    else:
        conn = _connect(db_path)
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row["content"] if row else None
