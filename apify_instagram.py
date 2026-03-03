# apify_instagram.py
"""Instagram scraper via Apify — vervangt Playwright-scraper voor concurrenten.

Gebruikt de apidojo/instagram-scraper Actor op Apify.
Vereist: APIFY_API_TOKEN in .env of Streamlit Secrets.
"""

import os
import sys
from datetime import datetime, timezone

from apify_client import ApifyClient

from competitors import IG_COMPETITORS

APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN", "")
ACTOR_ID = "apify/instagram-scraper"


def apify_scrape_ig_profiles(usernames: list, posts_per_profile: int = 300) -> dict:
    """Scrape Instagram profielen via Apify.

    Args:
        usernames: lijst van Instagram usernames (zonder @)
        posts_per_profile: max aantal posts per profiel

    Returns:
        dict per username met:
          - profile: {followers, following, posts_count}
          - posts: [{date, type, text, likes, comments, views, shortcode, ...}]
    """
    token = os.environ.get("APIFY_API_TOKEN", "") or APIFY_TOKEN
    if not token:
        raise RuntimeError("APIFY_API_TOKEN niet gevonden in environment")

    client = ApifyClient(token)

    clean = [u.lstrip("@") for u in usernames]
    run_input = {
        "directUrls": [f"https://www.instagram.com/{u}/" for u in clean],
        "resultsType": "posts",
        "resultsLimit": posts_per_profile,
        "addParentData": True,
    }

    print(f"  Apify Actor starten voor {len(usernames)} profiel(en)...")
    run = client.actor(ACTOR_ID).call(run_input=run_input)

    # Resultaten ophalen
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    print(f"  {len(items)} items ontvangen van Apify")

    # Groepeer per username
    results = {}
    for item in items:
        owner = (item.get("ownerUsername") or "").lower()
        if not owner:
            continue

        if owner not in results:
            results[owner] = {
                "profile": {
                    "followers": 0,
                    "following": 0,
                    "posts_count": 0,
                },
                "posts": [],
            }

        # Profiel-info uit parent data (eerste keer vullen)
        profile = results[owner]["profile"]
        if item.get("followersCount"):
            profile["followers"] = item["followersCount"]
        if item.get("followsCount"):
            profile["following"] = item["followsCount"]
        if item.get("postsCount"):
            profile["posts_count"] = item["postsCount"]

        # Post data mappen
        timestamp = item.get("timestamp")
        if not timestamp:
            continue

        # Apify levert ISO-8601 string of unix timestamp
        if isinstance(timestamp, (int, float)):
            date_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        else:
            date_str = str(timestamp)

        shortcode = item.get("shortCode") or item.get("id") or ""
        caption = (item.get("caption") or "")[:200]

        # Type mapping: Image/Sidecar → Foto, Video → Video
        raw_type = (item.get("type") or "").lower()
        post_type = "Video" if "video" in raw_type else "Foto"

        results[owner]["posts"].append({
            "date": date_str,
            "type": post_type,
            "text": caption,
            "likes": item.get("likesCount", 0) or 0,
            "comments": item.get("commentsCount", 0) or 0,
            "shares": 0,
            "reach": 0,
            "views": item.get("videoViewCount", 0) or 0,
            "clicks": 0,
            "shortcode": shortcode,
            "source": "apify",
        })

    # Sorteer posts per profiel (nieuwste eerst)
    for data in results.values():
        data["posts"].sort(key=lambda p: p["date"], reverse=True)

    return results


def apify_scrape_ig_competitor(key: str) -> dict:
    """Scrape een enkele IG-concurrent via Apify.

    Returns: {"posts": [...], "profile": {...}} in hetzelfde format als
    ig_scraper.scrape_ig_profile().
    """
    if key not in IG_COMPETITORS:
        raise ValueError(f"Onbekende IG-concurrent: {key}")

    username = IG_COMPETITORS[key]["username"]
    results = apify_scrape_ig_profiles([username])

    # Resultaat opzoeken (username is lowercase)
    data = results.get(username.lower())
    if data:
        return data

    # Fallback: misschien andere key in resultaten
    if results:
        return next(iter(results.values()))

    return {"profile": {"followers": 0, "following": 0, "posts_count": 0}, "posts": []}


# ── CLI test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    # Herlaad token na dotenv
    APIFY_TOKEN = os.environ.get("APIFY_API_TOKEN", "")

    target = sys.argv[1] if len(sys.argv) > 1 else "hillspet"

    # Check of het een competitor key is
    if target in IG_COMPETITORS:
        print(f"Apify scraping voor concurrent '{target}'...")
        result = apify_scrape_ig_competitor(target)
    else:
        print(f"Apify scraping voor @{target}...")
        result = apify_scrape_ig_profiles([target])
        result = result.get(target.lower(), {
            "profile": {"followers": 0}, "posts": []
        })

    profile = result.get("profile", {})
    posts = result.get("posts", [])

    print(f"\nProfiel: {profile}")
    print(f"\n{len(posts)} posts:\n")
    for i, post in enumerate(posts[:15], 1):
        date = post["date"][:10]
        print(f"  {i}. [{date}] {post['likes']} likes, "
              f"{post['comments']} reacties — {post['text'][:60]}")
