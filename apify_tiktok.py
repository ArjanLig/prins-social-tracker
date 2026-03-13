# apify_tiktok.py
"""TikTok scraper via Apify — vervangt yt-dlp scraper voor concurrenten.

Gebruikt de clockworks/tiktok-scraper Actor op Apify.
Vereist: APIFY_API_TOKEN in .env of Streamlit Secrets.
"""

import os
import sys
from datetime import datetime, timezone

from apify_client import ApifyClient

from competitors import TK_COMPETITORS

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN", "")
ACTOR_ID = "clockworks/tiktok-scraper"


def apify_scrape_tk_profiles(usernames: list, videos_per_profile: int = 50) -> dict:
    """Scrape TikTok profielen via Apify.

    Args:
        usernames: lijst van TikTok usernames (zonder @)
        videos_per_profile: max aantal video's per profiel

    Returns:
        dict per username met:
          - profile: {followers, following, likes, video_count, display_name}
          - posts: [{date, type, text, views, likes, comments, shares, ...}]
    """
    token = os.environ.get("APIFY_API_TOKEN", "") or APIFY_TOKEN
    if not token:
        raise RuntimeError("APIFY_API_TOKEN niet gevonden in environment")

    client = ApifyClient(token)

    clean = [u.lstrip("@") for u in usernames]
    run_input = {
        "profiles": clean,
        "resultsPerPage": videos_per_profile,
    }

    print(f"  Apify TikTok Actor starten voor {len(clean)} profiel(en)...")
    run = client.actor(ACTOR_ID).call(run_input=run_input)

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"  {len(items)} items ontvangen van Apify")

    # Groepeer per username
    results = {}
    for item in items:
        owner = (item.get("input") or "").lower()
        if not owner:
            # Fallback: probeer authorMeta
            author = item.get("authorMeta", {})
            owner = (author.get("name") or "").lower()
        if not owner:
            continue

        if owner not in results:
            results[owner] = {
                "profile": {
                    "display_name": "",
                    "followers": 0,
                    "following": 0,
                    "likes": 0,
                    "video_count": 0,
                },
                "posts": [],
            }

        # Profiel-info uit authorMeta (eerste keer vullen)
        profile = results[owner]["profile"]
        author = item.get("authorMeta", {})
        if author.get("fans"):
            profile["followers"] = int(author["fans"])
        if author.get("following"):
            profile["following"] = int(author["following"])
        if author.get("heart"):
            profile["likes"] = int(author["heart"])
        if author.get("video"):
            profile["video_count"] = int(author["video"])
        if author.get("nickName"):
            profile["display_name"] = author["nickName"]

        # Post data mappen
        ts = item.get("createTime")
        if not ts:
            continue

        if isinstance(ts, (int, float)):
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        else:
            date_str = item.get("createTimeISO") or str(ts)

        video_id = str(item.get("id", ""))
        caption = (item.get("text") or "")[:200]

        results[owner]["posts"].append({
            "date": date_str,
            "type": "Video",
            "text": caption,
            "likes": item.get("diggCount", 0) or 0,
            "comments": item.get("commentCount", 0) or 0,
            "shares": (item.get("shareCount", 0) or 0) + (item.get("repostCount", 0) or 0),
            "reach": 0,
            "views": item.get("playCount", 0) or 0,
            "clicks": 0,
            "id": video_id,
            "page": owner,
            "source": "apify",
        })

    # Sorteer posts per profiel (nieuwste eerst)
    for data in results.values():
        data["posts"].sort(key=lambda p: p["date"], reverse=True)

    return results


def apify_scrape_tk_competitor(key: str) -> dict:
    """Scrape een enkele TikTok-concurrent via Apify.

    Returns: {"profile": {...}, "posts": [...]}
    """
    if key not in TK_COMPETITORS:
        raise ValueError(f"Onbekende TK-concurrent: {key}")

    username = TK_COMPETITORS[key]["username"]
    results = apify_scrape_tk_profiles([username])

    data = results.get(username.lower())
    if data:
        return data

    if results:
        return next(iter(results.values()))

    return {"profile": {"followers": 0}, "posts": []}


# ── CLI test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    target = sys.argv[1] if len(sys.argv) > 1 else "edgardcooper"

    if target in TK_COMPETITORS:
        print(f"Apify TikTok scraping voor concurrent '{target}'...")
        result = apify_scrape_tk_competitor(target)
    else:
        print(f"Apify TikTok scraping voor @{target}...")
        result = apify_scrape_tk_profiles([target])
        result = result.get(target.lower(), {"profile": {"followers": 0}, "posts": []})

    profile = result.get("profile", {})
    posts = result.get("posts", [])

    print(f"\nProfiel: {profile}")
    print(f"\n{len(posts)} video's:\n")
    for i, post in enumerate(posts[:10], 1):
        date = post["date"][:10]
        print(f"  {i}. [{date}] {post['views']:,} views, {post['likes']} likes — {post['text'][:60]}")
