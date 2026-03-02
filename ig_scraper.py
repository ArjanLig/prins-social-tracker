# ig_scraper.py
"""Instagram scraper voor concurrenten via Playwright.

Gebruikt de bestaande Facebook browser-sessie om Instagram profielen
te laden en post-data te extraheren uit de GraphQL API responses.
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SESSION_DIR = Path(__file__).parent / ".fb_session"


def scrape_ig_profile(username: str, max_posts: int = 25) -> dict:
    """Scrape een Instagram profiel en recente posts.

    Returns dict met:
      - profile: {followers, following, posts_count}
      - posts: [{date, type, text, likes, comments, shares, shortcode, page, source}]
    """
    username = username.lstrip("@")
    api_data = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=True,
            viewport={"width": 1280, "height": 900},
            locale="nl-NL",
        )
        page = ctx.new_page()

        def capture(resp):
            url = resp.url
            if "instagram.com" in url and ("graphql" in url or "/api/v1/" in url):
                try:
                    api_data.append(resp.text())
                except Exception:
                    pass

        page.on("response", capture)

        print(f"  Navigeren naar instagram.com/{username}...")
        page.goto(f"https://www.instagram.com/{username}/",
                  wait_until="domcontentloaded", timeout=20000)
        time.sleep(5)

        # Sluit popups
        for sel in ['text=Niet nu', 'text=Not Now',
                    '[aria-label="Sluiten"]', '[aria-label="Close"]']:
            try:
                page.click(sel, timeout=2000)
                time.sleep(1)
            except Exception:
                pass

        # Scroll om meer posts te laden
        prev_height = 0
        for _ in range(12):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2.5)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break  # Geen nieuwe content meer
            prev_height = new_height

        # Profiel info uit body tekst
        profile = {"followers": 0, "following": 0, "posts_count": 0}
        try:
            body = page.inner_text("body")[:2000]
            fm = re.search(
                r'([\d.,]+)\s*([KkMm])?\s*(?:volgers|followers)', body, re.I)
            if fm:
                num = fm.group(1)
                suffix = (fm.group(2) or "").lower()
                raw = float(num.replace(".", "").replace(",", "."))
                if suffix == "k":
                    profile["followers"] = int(raw * 1_000)
                elif suffix == "m":
                    profile["followers"] = int(raw * 1_000_000)
                else:
                    profile["followers"] = int(raw)
            pm = re.search(r'([\d.,]+)\s*(?:berichten|posts)', body, re.I)
            if pm:
                profile["posts_count"] = int(
                    pm.group(1).replace(".", "").replace(",", ""))
        except Exception:
            pass

        ctx.close()

    # Parse posts uit API responses
    full = "\n".join(api_data)
    posts = _parse_ig_posts(full, max_posts)
    print(f"  {len(posts)} posts gevonden, {profile['followers']:,} volgers")

    return {"profile": profile, "posts": posts}


def _parse_ig_posts(text: str, max_posts: int) -> list[dict]:
    """Extraheer posts met metrics uit Instagram GraphQL response data."""
    posts = {}

    # Zoek posts via edge_media_to_comment (uniek per post)
    for m in re.finditer(
            r'"edge_media_to_comment":\{"count":(\d+)\}', text):
        idx = m.start()
        block = text[max(0, idx - 3000):idx + 500]

        comments = int(m.group(1))

        # Likes
        likes_m = re.search(
            r'"edge_liked_by":\{"count":(\d+)\}'
            r'|"edge_media_preview_like":\{"count":(\d+)\}',
            block)
        likes = int(likes_m.group(1) or likes_m.group(2)) if likes_m else 0

        # Timestamp
        ts_m = re.search(r'"taken_at_timestamp":(\d+)', block)
        ts = int(ts_m.group(1)) if ts_m else 0
        if ts == 0:
            continue
        date = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        # Shortcode (uniek post-id)
        sc_m = re.search(r'"shortcode":"([^"]+)"', block)
        shortcode = sc_m.group(1) if sc_m else ""
        if not shortcode:
            continue

        # Dedup op shortcode
        if shortcode in posts:
            continue

        # Tekst
        text_m = re.search(r'"text":"((?:[^"\\]|\\.){10,500})"', block)
        caption = ""
        if text_m:
            try:
                caption = json.loads(f'"{text_m.group(1)}"')
            except (json.JSONDecodeError, ValueError):
                caption = text_m.group(1)

        # Type
        is_video = '"is_video":true' in block
        post_type = "Video" if is_video else "Foto"

        posts[shortcode] = {
            "date": date,
            "type": post_type,
            "text": caption[:200],
            "likes": likes,
            "comments": comments,
            "shares": 0,
            "reach": 0,
            "views": 0,
            "clicks": 0,
            "shortcode": shortcode,
            "source": "scraper",
        }

    # Sorteer nieuwste eerst en limiteer
    result = sorted(posts.values(), key=lambda p: p["date"], reverse=True)
    return result[:max_posts]


if __name__ == "__main__":
    import sys
    username = sys.argv[1] if len(sys.argv) > 1 else "hillspet"
    print(f"Scraping Instagram @{username}...")
    result = scrape_ig_profile(username)
    print(f"\nProfiel: {result['profile']}")
    print(f"\n{len(result['posts'])} posts:\n")
    for i, post in enumerate(result["posts"], 1):
        date = post["date"][:10]
        print(f"  {i}. [{date}] {post['likes']} likes, "
              f"{post['comments']} reacties — {post['text'][:60]}")
