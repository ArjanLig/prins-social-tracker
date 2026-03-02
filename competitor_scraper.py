# competitor_scraper.py
"""Orchestratie van Facebook + TikTok scraping voor concurrenten."""

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from competitors import COMPETITORS
from database import DEFAULT_DB, init_db, insert_posts, save_follower_snapshot
from fb_scraper import scrape_fb_page_posts
from tiktok_api import tiktok_get_user_info, tiktok_get_videos


def scrape_competitor(key: str) -> dict:
    """Scrape Facebook + TikTok voor een enkele concurrent.

    Returns dict met resultaten: {"fb_posts": int, "tiktok_posts": int,
                                   "fb_followers": int|None, "tiktok_followers": int|None}
    """
    if key not in COMPETITORS:
        print(f"Onbekende concurrent: {key}")
        return {}

    comp = COMPETITORS[key]
    name = comp["name"]
    result = {
        "fb_posts": 0, "tiktok_posts": 0,
        "fb_followers": None, "tiktok_followers": None,
    }

    # ── Facebook ──
    fb_slug = comp.get("fb_slug")
    if fb_slug:
        print(f"\n[{name}] Facebook scraping ({fb_slug})...")
        try:
            fb_data = scrape_fb_page_posts(fb_slug, max_posts=50, max_scrolls=15)
            page_info = fb_data.get("page_info", {})
            fb_posts = fb_data.get("posts", [])

            # Volgers opslaan
            fb_followers = page_info.get("followers", 0)
            if fb_followers > 0:
                current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                save_follower_snapshot(DEFAULT_DB, "facebook", key,
                                       fb_followers, month=current_month)
                result["fb_followers"] = fb_followers
                print(f"  Volgers: {fb_followers:,}")

            # Posts opslaan
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
                result["fb_posts"] = inserted
                print(f"  {inserted} posts opgeslagen (van {len(fb_posts)} gevonden)")
        except Exception as e:
            print(f"  Facebook fout: {e}")

    # ── TikTok ──
    tiktok_user = comp.get("tiktok_username")
    if tiktok_user:
        print(f"\n[{name}] TikTok scraping (@{tiktok_user})...")
        try:
            # Profiel info (volgers)
            user_info = tiktok_get_user_info(tiktok_user)
            if user_info and "follower_count" in user_info:
                count = user_info["follower_count"]
                current_month = datetime.now(timezone.utc).strftime("%Y-%m")
                save_follower_snapshot(DEFAULT_DB, "tiktok", key,
                                       count, month=current_month)
                result["tiktok_followers"] = count
                print(f"  Volgers: {count:,}")

            # Video's
            videos = tiktok_get_videos(tiktok_user, page=key)
            if videos:
                inserted = insert_posts(DEFAULT_DB, videos, "tiktok")
                result["tiktok_posts"] = inserted
                print(f"  {inserted} video's opgeslagen (van {len(videos)} gevonden)")
        except Exception as e:
            print(f"  TikTok fout: {e}")

    return result


def scrape_all_competitors() -> dict[str, dict]:
    """Scrape alle concurrenten. Returns {key: result_dict}."""
    results = {}
    for key in COMPETITORS:
        results[key] = scrape_competitor(key)
    return results


if __name__ == "__main__":
    init_db()

    # CLI: optioneel een specifieke concurrent meegeven
    if len(sys.argv) > 1:
        target = sys.argv[1].lower()
        if target in COMPETITORS:
            result = scrape_competitor(target)
            print(f"\nResultaat {target}: {result}")
        else:
            print(f"Onbekende concurrent: {target}")
            print(f"Beschikbaar: {', '.join(COMPETITORS.keys())}")
    else:
        print("Alle concurrenten scrapen...\n")
        results = scrape_all_competitors()
        print("\n=== Samenvatting ===")
        for key, res in results.items():
            name = COMPETITORS[key]["name"]
            print(f"{name}: FB {res['fb_posts']} posts, TikTok {res['tiktok_posts']} posts")
