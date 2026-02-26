"""TikTok scraper voor Prins Social Tracker.

Haalt profiel-stats op via de publieke TikTok-pagina (hidden JSON) en
video-statistieken via yt-dlp.  Geen OAuth tokens of API-goedkeuring nodig.
"""

import json
import re
import subprocess
from datetime import datetime, timezone

import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

_REHYDRATION_PATTERN = re.compile(
    r'<script\s+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _fetch_page_json(url: str) -> dict | None:
    """Fetch een TikTok-pagina en extraheer de rehydration JSON."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception:
        return None

    match = _REHYDRATION_PATTERN.search(resp.text)
    if not match:
        return None

    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, IndexError):
        return None


def tiktok_get_user_info(username: str) -> dict | None:
    """Haal TikTok profiel-stats op voor een username (via pagina-scrape).

    Returns dict met display_name, follower_count, following_count,
    likes_count, video_count bij succes, None bij falen.
    """
    username = username.lstrip("@")
    data = _fetch_page_json(f"https://www.tiktok.com/@{username}")
    if not data:
        return None

    try:
        user_detail = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]
        user_info = user_detail["userInfo"]
        user = user_info.get("user", {})
        stats = user_info.get("stats", {})
        return {
            "display_name": user.get("nickname", username),
            "follower_count": int(stats.get("followerCount", 0)),
            "following_count": int(stats.get("followingCount", 0)),
            "likes_count": int(stats.get("heartCount", 0) or stats.get("heart", 0)),
            "video_count": int(stats.get("videoCount", 0)),
        }
    except (KeyError, TypeError, ValueError):
        return None


def tiktok_get_videos(username: str, max_count: int = 20) -> list[dict]:
    """Haal recente TikTok video's op met metrics via yt-dlp.

    Mapt velden naar het interne post-formaat:
      view_count   -> views
      like_count   -> likes
      comment_count -> comments
      repost_count -> shares
      reach        -> 0 (niet beschikbaar)
      clicks       -> 0 (niet beschikbaar)
    """
    username = username.lstrip("@")
    try:
        result = subprocess.run(
            [
                "python3", "-m", "yt_dlp",
                "--dump-json",
                "--flat-playlist",
                "--no-download",
                "--playlist-end", str(max_count),
                f"https://www.tiktok.com/@{username}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    posts = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts = v.get("timestamp", 0)
        if isinstance(ts, (int, float)) and ts > 0:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            date_str = dt.isoformat()
        else:
            date_str = ""

        desc = v.get("title") or v.get("description") or ""
        posts.append({
            "date": date_str,
            "type": "Video",
            "text": desc[:200],
            "reach": 0,
            "views": v.get("view_count", 0) or 0,
            "likes": v.get("like_count", 0) or 0,
            "comments": v.get("comment_count", 0) or 0,
            "shares": v.get("repost_count", 0) or 0,
            "clicks": 0,
            "page": "prins",
            "source": "scraper",
        })
    return posts
