# competitor_scraper.py
"""Orchestratie van Facebook + TikTok + Instagram scraping voor concurrenten.

Per-kanaal configuratie: verschillende concurrenten per platform.
"""

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from competitors import (
    FB_COMPETITORS,
    IG_COMPETITORS,
    TK_COMPETITORS,
    get_competitor_name,
)
from database import DEFAULT_DB, init_db, insert_posts, save_follower_snapshot

# Apify als primaire bron voor IG + TikTok; fallback naar lokale scrapers
_USE_APIFY = bool(os.environ.get("APIFY_API_TOKEN"))
if _USE_APIFY:
    from apify_instagram import apify_scrape_ig_competitor
    from apify_tiktok import apify_scrape_tk_profiles


def _import_fb_scraper():
    from fb_scraper import scrape_fb_page_posts
    return scrape_fb_page_posts


def _import_ig_scraper():
    from ig_scraper import scrape_ig_profile
    return scrape_ig_profile


def _import_tiktok_api():
    from tiktok_api import tiktok_get_user_info, tiktok_get_videos
    return tiktok_get_user_info, tiktok_get_videos


# ── Facebook ──────────────────────────────────────────────────────────

def scrape_fb_competitor(key: str) -> dict:
    """Scrape Facebook voor een enkele concurrent.

    Returns dict met posts en followers.
    """
    if key not in FB_COMPETITORS:
        print(f"Onbekende FB-concurrent: {key}")
        return {"posts": 0, "followers": None}

    comp = FB_COMPETITORS[key]
    name = comp["name"]
    slug = comp["slug"]
    result = {"posts": 0, "followers": None}

    print(f"\n[{name}] Facebook scraping ({slug})...")
    try:
        scrape_fb_page_posts = _import_fb_scraper()
        fb_data = scrape_fb_page_posts(slug, max_posts=50, max_scrolls=15)
        page_info = fb_data.get("page_info", {})
        fb_posts = fb_data.get("posts", [])

        fb_followers = page_info.get("followers", 0)
        if fb_followers > 0:
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            save_follower_snapshot(DEFAULT_DB, "facebook", key,
                                   fb_followers, month=current_month)
            result["followers"] = fb_followers
            print(f"  Volgers: {fb_followers:,}")

        if fb_posts:
            post_dicts = []
            for p in fb_posts:
                post_dicts.append({
                    "id": p.get("id", ""),
                    "date": p.get("date", ""),
                    "type": p.get("type", "Post"),
                    "text": (p.get("text") or "")[:200],
                    "reach": 0,
                    "views": p.get("views", 0) or 0,
                    "likes": p.get("likes", 0) or 0,
                    "comments": p.get("comments", 0) or 0,
                    "shares": p.get("shares", 0) or 0,
                    "clicks": 0,
                    "page": key,
                    "source": "scraper",
                })
            inserted = insert_posts(DEFAULT_DB, post_dicts, "facebook")
            result["posts"] = inserted
            print(f"  {inserted} posts opgeslagen (van {len(fb_posts)} gevonden)")
    except Exception as e:
        print(f"  Facebook fout: {e}")

    return result


def scrape_fb_all() -> dict:
    """Scrape Facebook voor alle FB-concurrenten."""
    return {key: scrape_fb_competitor(key) for key in FB_COMPETITORS}


# ── Instagram ─────────────────────────────────────────────────────────

def scrape_ig_competitor(key: str) -> dict:
    """Scrape Instagram voor een enkele concurrent.

    Gebruikt Apify als APIFY_API_TOKEN gezet is, anders Playwright fallback.
    """
    if key not in IG_COMPETITORS:
        print(f"Onbekende IG-concurrent: {key}")
        return {"posts": 0, "followers": None}

    comp = IG_COMPETITORS[key]
    name = comp["name"]
    username = comp["username"]
    result = {"posts": 0, "followers": None}

    source = "Apify" if _USE_APIFY else "Playwright"
    print(f"\n[{name}] Instagram scraping via {source} (@{username})...")
    try:
        if _USE_APIFY:
            ig_data = apify_scrape_ig_competitor(key)
        else:
            scrape_ig_profile = _import_ig_scraper()
            ig_data = scrape_ig_profile(username)

        profile = ig_data.get("profile", {})
        ig_posts = ig_data.get("posts", [])

        ig_followers = profile.get("followers", 0)
        if ig_followers > 0:
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            save_follower_snapshot(DEFAULT_DB, "instagram", key,
                                   ig_followers, month=current_month)
            result["followers"] = ig_followers
            print(f"  Volgers: {ig_followers:,}")

        if ig_posts:
            post_dicts = []
            for p in ig_posts:
                post_dicts.append({
                    "id": p.get("shortcode", ""),
                    "date": p.get("date", ""),
                    "type": p.get("type", "Foto"),
                    "text": (p.get("text") or "")[:200],
                    "reach": 0,
                    "views": p.get("views", 0) or 0,
                    "likes": p.get("likes", 0) or 0,
                    "comments": p.get("comments", 0) or 0,
                    "shares": 0,
                    "clicks": 0,
                    "page": key,
                    "source": p.get("source", "scraper"),
                })
            inserted = insert_posts(DEFAULT_DB, post_dicts, "instagram")
            result["posts"] = inserted
            print(f"  {inserted} posts opgeslagen (van {len(ig_posts)} gevonden)")
    except Exception as e:
        print(f"  Instagram fout: {e}")

    return result


def scrape_ig_all() -> dict:
    """Scrape Instagram voor alle IG-concurrenten.

    Met Apify: één batch-call voor alle profielen tegelijk.
    Zonder Apify: per profiel apart (Playwright fallback).
    """
    if not _USE_APIFY:
        return {key: scrape_ig_competitor(key) for key in IG_COMPETITORS}

    from apify_instagram import apify_scrape_ig_profiles

    # Eén batch Apify call voor alle concurrenten
    username_to_key = {}
    for key, comp in IG_COMPETITORS.items():
        username_to_key[comp["username"].lower()] = key

    usernames = [comp["username"] for comp in IG_COMPETITORS.values()]
    print(f"\n[Apify batch] Instagram scraping voor {len(usernames)} concurrenten...")

    try:
        all_data = apify_scrape_ig_profiles(usernames, posts_per_profile=30)
    except Exception as e:
        print(f"  Apify batch fout: {e}")
        return {key: {"posts": 0, "followers": None} for key in IG_COMPETITORS}

    # Resultaten per concurrent verwerken
    results = {}
    for username_lower, data in all_data.items():
        key = username_to_key.get(username_lower)
        if not key:
            continue

        result = {"posts": 0, "followers": None}
        profile = data.get("profile", {})
        ig_posts = data.get("posts", [])

        ig_followers = profile.get("followers", 0)
        if ig_followers > 0:
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            save_follower_snapshot(DEFAULT_DB, "instagram", key,
                                   ig_followers, month=current_month)
            result["followers"] = ig_followers

        if ig_posts:
            post_dicts = []
            for p in ig_posts:
                post_dicts.append({
                    "id": p.get("shortcode", ""),
                    "date": p.get("date", ""),
                    "type": p.get("type", "Foto"),
                    "text": (p.get("text") or "")[:200],
                    "reach": 0,
                    "views": p.get("views", 0) or 0,
                    "likes": p.get("likes", 0) or 0,
                    "comments": p.get("comments", 0) or 0,
                    "shares": 0,
                    "clicks": 0,
                    "page": key,
                    "source": p.get("source", "apify"),
                })
            result["posts"] = insert_posts(DEFAULT_DB, post_dicts, "instagram")

        name = IG_COMPETITORS[key]["name"]
        print(f"  {name}: {result['posts']} posts, volgers: {result.get('followers', '—')}")
        results[key] = result

    # Concurrenten zonder resultaten
    for key in IG_COMPETITORS:
        if key not in results:
            results[key] = {"posts": 0, "followers": None}

    return results


# ── TikTok ────────────────────────────────────────────────────────────

def scrape_tk_competitor(key: str) -> dict:
    """Scrape TikTok voor een enkele concurrent.

    Gebruikt Apify als APIFY_API_TOKEN gezet is, anders yt-dlp fallback.
    """
    if key not in TK_COMPETITORS:
        print(f"Onbekende TikTok-concurrent: {key}")
        return {"posts": 0, "followers": None}

    comp = TK_COMPETITORS[key]
    name = comp["name"]
    username = comp["username"]
    result = {"posts": 0, "followers": None}

    source = "Apify" if _USE_APIFY else "yt-dlp"
    print(f"\n[{name}] TikTok scraping via {source} (@{username})...")
    try:
        if _USE_APIFY:
            from apify_tiktok import apify_scrape_tk_competitor
            tk_data = apify_scrape_tk_competitor(key)
            profile = tk_data.get("profile", {})
            tk_posts = tk_data.get("posts", [])

            tk_followers = profile.get("followers", 0)
            if tk_followers > 0:
                current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                save_follower_snapshot(DEFAULT_DB, "tiktok", key,
                                       tk_followers, month=current_month)
                result["followers"] = tk_followers
                print(f"  Volgers: {tk_followers:,}")

            if tk_posts:
                # Zorg dat page correct is (key, niet username)
                for p in tk_posts:
                    p["page"] = key
                inserted = insert_posts(DEFAULT_DB, tk_posts, "tiktok")
                result["posts"] = inserted
                print(f"  {inserted} video's opgeslagen (van {len(tk_posts)} gevonden)")
        else:
            tiktok_get_user_info, tiktok_get_videos = _import_tiktok_api()
            user_info = tiktok_get_user_info(username)
            if user_info and "follower_count" in user_info:
                count = user_info["follower_count"]
                current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                save_follower_snapshot(DEFAULT_DB, "tiktok", key,
                                       count, month=current_month)
                result["followers"] = count
                print(f"  Volgers: {count:,}")

            videos = tiktok_get_videos(username, page=key)
            if videos:
                inserted = insert_posts(DEFAULT_DB, videos, "tiktok")
                result["posts"] = inserted
                print(f"  {inserted} video's opgeslagen (van {len(videos)} gevonden)")
    except Exception as e:
        print(f"  TikTok fout: {e}")

    return result


def scrape_tk_all() -> dict:
    """Scrape TikTok voor alle TK-concurrenten.

    Met Apify: één batch-call voor alle profielen tegelijk.
    Zonder Apify: per profiel apart (yt-dlp fallback).
    """
    if not _USE_APIFY:
        return {key: scrape_tk_competitor(key) for key in TK_COMPETITORS}

    # Eén batch Apify call voor alle concurrenten
    username_to_key = {}
    for key, comp in TK_COMPETITORS.items():
        username_to_key[comp["username"].lower()] = key

    usernames = [comp["username"] for comp in TK_COMPETITORS.values()]
    print(f"\n[Apify batch] TikTok scraping voor {len(usernames)} concurrenten...")

    try:
        all_data = apify_scrape_tk_profiles(usernames, videos_per_profile=20)
    except Exception as e:
        print(f"  Apify TikTok batch fout: {e}")
        return {key: {"posts": 0, "followers": None} for key in TK_COMPETITORS}

    results = {}
    for username_lower, data in all_data.items():
        key = username_to_key.get(username_lower)
        if not key:
            continue

        result = {"posts": 0, "followers": None}
        profile = data.get("profile", {})
        tk_posts = data.get("posts", [])

        tk_followers = profile.get("followers", 0)
        if tk_followers > 0:
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            save_follower_snapshot(DEFAULT_DB, "tiktok", key,
                                   tk_followers, month=current_month)
            result["followers"] = tk_followers

        if tk_posts:
            for p in tk_posts:
                p["page"] = key
            result["posts"] = insert_posts(DEFAULT_DB, tk_posts, "tiktok")

        name = TK_COMPETITORS[key]["name"]
        print(f"  {name}: {result['posts']} video's, volgers: {result.get('followers', '—')}")
        results[key] = result

    for key in TK_COMPETITORS:
        if key not in results:
            results[key] = {"posts": 0, "followers": None}

    return results


# ── Gecombineerd ──────────────────────────────────────────────────────

def scrape_platform(platform: str, key: str = "") -> dict:
    """Scrape een specifiek platform (optioneel voor een enkele concurrent)."""
    if platform == "facebook":
        if key:
            return {key: scrape_fb_competitor(key)}
        return scrape_fb_all()
    elif platform == "instagram":
        if key:
            return {key: scrape_ig_competitor(key)}
        return scrape_ig_all()
    elif platform == "tiktok":
        if key:
            return {key: scrape_tk_competitor(key)}
        return scrape_tk_all()
    else:
        print(f"Onbekend platform: {platform}")
        return {}


def scrape_all_competitors() -> dict:
    """Scrape alle platformen voor alle concurrenten.

    Returns: {"facebook": {key: result}, "instagram": {...}, "tiktok": {...}}
    """
    return {
        "facebook": scrape_fb_all(),
        "instagram": scrape_ig_all(),
        "tiktok": scrape_tk_all(),
    }


# ── CLI ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    args = [a.lower() for a in sys.argv[1:]]

    if not args:
        # Alles scrapen
        print("Alle concurrenten scrapen (alle platformen)...\n")
        results = scrape_all_competitors()
        print("\n=== Samenvatting ===")
        for platform, platform_results in results.items():
            print(f"\n{platform.upper()}:")
            for key, res in platform_results.items():
                name = get_competitor_name(key)
                print(f"  {name}: {res.get('posts', 0)} posts, "
                      f"volgers: {res.get('followers', '—')}")

    elif args[0] in ("facebook", "instagram", "tiktok"):
        platform = args[0]
        key = args[1] if len(args) > 1 else ""
        if key:
            print(f"{platform.capitalize()} scraping voor {key}...")
            result = scrape_platform(platform, key)
            print(f"\nResultaat: {result}")
        else:
            print(f"Alle {platform.capitalize()} concurrenten scrapen...")
            results = scrape_platform(platform)
            print(f"\n=== {platform.capitalize()} Samenvatting ===")
            for key, res in results.items():
                name = get_competitor_name(key)
                print(f"  {name}: {res.get('posts', 0)} posts, "
                      f"volgers: {res.get('followers', '—')}")

    else:
        # Probeer als competitor key (backward compat)
        target = args[0]
        found = False
        for platform, comps in [("facebook", FB_COMPETITORS),
                                 ("instagram", IG_COMPETITORS),
                                 ("tiktok", TK_COMPETITORS)]:
            if target in comps:
                scrape_platform(platform, target)
                found = True
        if not found:
            print(f"Onbekende concurrent: {target}")
            print(f"\nGebruik: python3 competitor_scraper.py [platform] [key]")
            print(f"  Platformen: facebook, instagram, tiktok")
            print(f"  Facebook: {', '.join(FB_COMPETITORS.keys())}")
            print(f"  Instagram: {', '.join(IG_COMPETITORS.keys())}")
            print(f"  TikTok: {', '.join(TK_COMPETITORS.keys())}")
