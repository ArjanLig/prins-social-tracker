"""TikTok API client voor Prins Social Tracker."""

import requests

TIKTOK_BASE_URL = "https://open.tiktokapis.com/v2"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def tiktok_check_token(access_token: str) -> bool:
    """Check of een TikTok access token nog geldig is."""
    if not access_token:
        return False
    try:
        resp = requests.get(
            f"{TIKTOK_BASE_URL}/user/info/",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "display_name"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def tiktok_refresh_access_token(
    client_key: str, client_secret: str, refresh_token: str
) -> dict | None:
    """Vernieuw een TikTok access token via de refresh token.

    Returns dict met access_token, refresh_token, expires_in bij succes, None bij falen.
    """
    if not all([client_key, client_secret, refresh_token]):
        return None
    try:
        resp = requests.post(
            TIKTOK_TOKEN_URL,
            json={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" in data:
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token", refresh_token),
                "expires_in": data.get("expires_in", 86400),
            }
    except Exception:
        pass
    return None


def tiktok_get_auth_url(client_key: str, redirect_uri: str) -> str:
    """Genereer de TikTok OAuth autorisatie-URL."""
    scope = "user.info.basic,video.list"
    return (
        f"https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={client_key}"
        f"&scope={scope}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
    )


def tiktok_get_user_info(access_token: str) -> dict | None:
    """Haal TikTok gebruikersinfo op (display_name, follower_count, etc.)."""
    if not access_token:
        return None
    try:
        resp = requests.get(
            f"{TIKTOK_BASE_URL}/user/info/",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"fields": "display_name,follower_count,following_count,likes_count,video_count"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {}).get("user", {})
        if data:
            return data
    except Exception:
        pass
    return None


def tiktok_get_videos(access_token: str, max_count: int = 20) -> list[dict]:
    """Haal recente TikTok video's op met metrics.

    Mapt TikTok-velden naar het interne post-formaat:
      view_count  -> impressions (weergaven)
      like_count  -> likes
      comment_count -> comments
      share_count -> shares
      reach       -> 0 (TikTok biedt geen bereik)
      clicks      -> 0 (niet beschikbaar via API)
    """
    if not access_token:
        return []
    try:
        resp = requests.post(
            f"{TIKTOK_BASE_URL}/video/list/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "max_count": max_count,
                "fields": [
                    "id", "title", "create_time",
                    "view_count", "like_count", "comment_count", "share_count",
                ],
            },
            timeout=15,
        )
        resp.raise_for_status()
        videos = resp.json().get("data", {}).get("videos", [])
        posts = []
        for v in videos:
            from datetime import datetime, timezone
            created = v.get("create_time", 0)
            if isinstance(created, (int, float)) and created > 0:
                dt = datetime.fromtimestamp(created, tz=timezone.utc)
                date_str = dt.isoformat()
            else:
                date_str = ""
            posts.append({
                "date": date_str,
                "type": "Video",
                "text": (v.get("title") or "")[:200],
                "reach": 0,
                "views": v.get("view_count", 0),
                "likes": v.get("like_count", 0),
                "comments": v.get("comment_count", 0),
                "shares": v.get("share_count", 0),
                "clicks": 0,
                "page": "prins",
                "source": "api",
            })
        return posts
    except Exception:
        return []
