#!/usr/bin/env python3
"""Eenmalige sync: haal alle posts op vanaf 2023 via de Meta Graph API."""

import os
import ssl
import time

import requests
import urllib3
from dotenv import load_dotenv

# SSL workaround voor macOS Python 3.14
urllib3.disable_warnings()
SESSION = requests.Session()
SESSION.verify = False

from database import DEFAULT_DB, init_db, insert_posts

load_dotenv()

FB_API_VERSION = "v21.0"
FB_BASE_URL = f"https://graph.facebook.com/{FB_API_VERSION}"

BRANDS = {
    "prins": {
        "token": os.getenv("PRINS_TOKEN"),
        "page_id": os.getenv("PRINS_PAGE_ID"),
    },
    "edupet": {
        "token": os.getenv("EDUPET_TOKEN"),
        "page_id": os.getenv("EDUPET_PAGE_ID"),
    },
}

SINCE = "2023-01-01"


def fetch_all_fb_posts(brand: str, page_id: str, token: str) -> list[dict]:
    """Haal alle Facebook posts op vanaf SINCE."""
    all_posts = []
    url = f"{FB_BASE_URL}/{page_id}/published_posts"
    params = {
        "fields": "message,created_time,shares,"
                  "likes.summary(true),comments.summary(true)",
        "limit": 25,
        "access_token": token,
    }

    page_num = 1
    keep_going = True
    while url and keep_going:
        print(f"  Facebook pagina {page_num}...", end=" ", flush=True)
        resp = SESSION.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        posts = data.get("data", [])
        print(f"{len(posts)} posts", flush=True)

        for post in posts:
            created = post.get("created_time", "")
            if created and created[:4] < "2023":
                keep_going = False
                break

            likes = post.get("likes", {}).get("summary", {}).get("total_count", 0)
            comments = post.get("comments", {}).get("summary", {}).get("total_count", 0)
            shares = post.get("shares", {}).get("count", 0)

            # Bereik apart ophalen per post
            reach = 0
            try:
                post_id = post.get("id")
                r = SESSION.get(
                    f"{FB_BASE_URL}/{post_id}/insights",
                    params={"metric": "post_impressions_unique", "access_token": token},
                    timeout=15,
                )
                if r.status_code == 200:
                    for ins in r.json().get("data", []):
                        if ins["name"] == "post_impressions_unique":
                            reach = ins["values"][0]["value"]
            except Exception:
                pass

            all_posts.append({
                "date": created,
                "type": "Post",
                "text": (post.get("message") or "")[:200],
                "reach": reach,
                "views": 0,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "clicks": 0,
                "page": brand,
                "source": "api",
            })
            time.sleep(0.2)  # rate limit per insight call

        # Volgende pagina
        next_url = data.get("paging", {}).get("next")
        if next_url and keep_going:
            url = next_url
            params = {}  # params zitten al in de next URL
            page_num += 1
            time.sleep(1)  # rate limit friendly
        else:
            break

    return all_posts


def fetch_all_ig_posts(brand: str, page_id: str, token: str) -> list[dict]:
    """Haal alle Instagram posts op vanaf SINCE."""
    # Haal IG business account ID op
    resp = SESSION.get(
        f"{FB_BASE_URL}/{page_id}",
        params={"fields": "instagram_business_account", "access_token": token},
        timeout=15,
    )
    resp.raise_for_status()
    ig_id = resp.json().get("instagram_business_account", {}).get("id")
    if not ig_id:
        print("  Geen Instagram business account gevonden")
        return []

    print(f"  Instagram account ID: {ig_id}")

    all_posts = []
    url = f"{FB_BASE_URL}/{ig_id}/media"
    params = {
        "fields": "caption,timestamp,like_count,comments_count,"
                  "media_type,insights.metric(reach)",
        "limit": 50,
        "access_token": token,
    }

    page_num = 1
    keep_going = True
    while url and keep_going:
        print(f"  Instagram pagina {page_num}...", end=" ", flush=True)
        resp = SESSION.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        posts = data.get("data", [])
        print(f"{len(posts)} posts")

        for post in posts:
            ts = post.get("timestamp", "")
            # Stop als we voor 2023 zijn
            if ts and ts[:4] < "2023":
                keep_going = False
                break

            reach = 0
            for ins in post.get("insights", {}).get("data", []):
                if ins["name"] == "reach":
                    reach = ins["values"][0]["value"]
            all_posts.append({
                "date": ts,
                "type": post.get("media_type", "Post"),
                "text": (post.get("caption") or "")[:200],
                "reach": reach,
                "views": 0,
                "likes": post.get("like_count", 0),
                "comments": post.get("comments_count", 0),
                "shares": 0,
                "clicks": 0,
                "page": brand,
                "source": "api",
            })

        # Volgende pagina
        next_url = data.get("paging", {}).get("next")
        if next_url and keep_going:
            url = next_url
            params = {}
            page_num += 1
            time.sleep(0.5)
        else:
            break

    return all_posts


def main():
    init_db()
    print(f"=== Historische sync vanaf {SINCE} ===\n")

    for brand, config in BRANDS.items():
        token = config["token"]
        page_id = config["page_id"]
        if not token or not page_id:
            print(f"{brand}: geen token/page_id geconfigureerd, overgeslagen")
            continue

        print(f"--- {brand.upper()} ---")

        # Facebook
        print(f"\nFacebook posts ophalen...")
        fb_posts = fetch_all_fb_posts(brand, page_id, token)
        if fb_posts:
            new = insert_posts(DEFAULT_DB, fb_posts, "facebook")
            print(f"  Totaal: {len(fb_posts)} posts, {new} nieuw opgeslagen")
        else:
            print("  Geen posts gevonden")

        # Instagram
        print(f"\nInstagram posts ophalen...")
        ig_posts = fetch_all_ig_posts(brand, page_id, token)
        if ig_posts:
            new = insert_posts(DEFAULT_DB, ig_posts, "instagram")
            print(f"  Totaal: {len(ig_posts)} posts, {new} nieuw opgeslagen")
        else:
            print("  Geen posts gevonden")

        print()

    print("=== Klaar! ===")


if __name__ == "__main__":
    main()
