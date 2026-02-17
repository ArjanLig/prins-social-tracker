"""
Facebook Page Scraper via Playwright.
Gebruikt een opgeslagen browser-sessie om posts te scrapen.
Eenmalig inloggen via --login, daarna draait alles automatisch headless.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

SESSION_DIR = Path(__file__).parent / ".fb_session"


# ─── Sessie beheer ──────────────────────────────────────────────────

def login():
    """Open een zichtbaar browser-venster zodat de gebruiker kan inloggen."""
    SESSION_DIR.mkdir(exist_ok=True)
    print("Een browser-venster wordt geopend.")
    print("Log in op Facebook en sluit daarna het venster.\n")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="nl-NL",
        )
        page = ctx.new_page()
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
        try:
            page.wait_for_event("close", timeout=300_000)
        except Exception:
            pass
        ctx.close()

    print("Sessie opgeslagen.")


def has_session() -> bool:
    return SESSION_DIR.exists() and any(SESSION_DIR.iterdir())


# ─── Scraper ────────────────────────────────────────────────────────

def scrape_fb_page_posts(page_name: str, max_posts: int = 25,
                         scroll_pause: float = 2.5,
                         max_scrolls: int = 15) -> dict:
    """
    Scrape posts van een Facebook-pagina.

    Returns dict met:
      - page_info: {name, likes, followers}
      - posts: [{id, text, date, likes, comments, shares, reactions, url}, ...]
    """
    if not has_session():
        print("Geen Facebook-sessie gevonden. Draai eerst: python3 fb_scraper.py --login")
        return {"page_info": {}, "posts": []}

    raw_responses = []
    page_url = f"https://www.facebook.com/{page_name}"

    def capture_response(response):
        url = response.url
        if "graphql" in url or "api/graphql" in url:
            try:
                raw_responses.append(response.text())
            except Exception:
                pass

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=True,
            viewport={"width": 1280, "height": 900},
            locale="nl-NL",
        )
        page = ctx.new_page()
        page.on("response", capture_response)

        print(f"  Navigeren naar {page_url}...")
        page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)

        # Sluit popups
        for selector in ['[aria-label="Sluiten"]', '[aria-label="Close"]']:
            try:
                page.click(selector, timeout=2000)
                time.sleep(1)
                break
            except Exception:
                pass

        # Scroll om posts te laden
        print(f"  Posts laden...")
        prev_height = 0
        for _ in range(max_scrolls):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(scroll_pause)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break
            prev_height = new_height

        page_info = _extract_page_info(page)
        ctx.close()

    # Parse alle response data
    full_text = "\n".join(raw_responses)
    posts = _parse_posts_from_raw(full_text, max_posts)
    print(f"  {len(posts)} posts gevonden")

    return {"page_info": page_info, "posts": posts}


def _extract_page_info(page) -> dict:
    info = {"name": "", "likes": 0, "followers": 0}
    try:
        title = page.title() or ""
        # Verwijder notificatie-badge "(1)" etc. en "Facebook"
        name = re.sub(r'^\(\d+\)\s*', '', title)
        info["name"] = (name.split(" | ")[0].split(" - ")[0]
                        .replace("Facebook", "").strip())

        body = page.inner_text("body")[:2000]
        # "37 d. volgers" = 37K (d. = duizend)
        fm = re.search(r'([\d.,]+)\s*(?:d\.)?\s*(?:volgers|followers)', body, re.I)
        if fm:
            num = fm.group(1)
            if "d." in fm.group(0):
                info["followers"] = int(float(num.replace(".", "").replace(",", ".")) * 1000)
            else:
                info["followers"] = _parse_number(num)
        lm = re.search(r'([\d.,]+)\s*(?:vind-ik-leuks|likes)', body, re.I)
        if lm:
            info["likes"] = _parse_number(lm.group(1))
    except Exception:
        pass
    return info


def _parse_number(s: str) -> int:
    s = s.strip().upper().replace(".", "").replace(",", "")
    if s.endswith("K"):
        return int(float(s[:-1]) * 1000)
    if s.endswith("M"):
        return int(float(s[:-1]) * 1_000_000)
    try:
        return int(s)
    except ValueError:
        return 0


# ─── Data extractie ─────────────────────────────────────────────────

def _parse_posts_from_raw(text: str, max_posts: int) -> list[dict]:
    """
    Extraheer posts uit de ruwe GraphQL response tekst.

    Facebook structuur (NDJSON, geneste relay objects):
    - post_id + comet_sections bevat de post
    - creation_time zit binnen ~5000 chars van post_id
    - subscription_target_id (= post_id) linkt naar feedback (reacties/shares)
    - message.text zit in "message":{"delight_ranges":[],...,"text":"..."}
    """
    posts = {}

    # Stap 1: Vind alle unieke post_ids
    all_pids = set(re.findall(r'"post_id":"(\d+)"', text))

    # Stap 2: Voor elke post_id, doorzoek ALLE occurrences voor creation_time + url
    for pid in all_pids:
        posts[pid] = {
            "id": pid, "text": "", "date": "", "type": "", "views": 0,
            "likes": 0, "comments": 0, "shares": 0, "reactions": {}, "url": "",
        }

        for m in re.finditer(f'"post_id":"{pid}"', text):
            if posts[pid]["date"]:
                break  # Al gevonden
            start = max(0, m.start() - 8000)
            end = min(len(text), m.end() + 8000)
            block = text[start:end]

            ct = re.search(r'"creation_time":(\d{10})', block)
            if ct:
                ts = int(ct.group(1))
                posts[pid]["date"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

            url_m = re.search(r'"url":"(https:\\/\\/www\.facebook\.com\\/[^"]*?\\/posts\\/[^"]*?)"', block)
            if url_m:
                posts[pid]["url"] = url_m.group(1).replace("\\/", "/")

            # Post type detectie via __typename nabij attachments
            if not posts[pid]["type"]:
                type_map = {
                    "Photo": "Foto",
                    "Video": "Video",
                    "Reel": "Reel",
                    "ExternalUrl": "Link",
                    "Share": "Gedeeld",
                    "Album": "Album",
                    "ProfilePicture": "Profielfoto",
                    "CoverPhoto": "Omslagfoto",
                    "Event": "Evenement",
                }
                for tn in re.finditer(r'"__typename":"(\w+)"', block):
                    matched_type = type_map.get(tn.group(1))
                    if matched_type:
                        posts[pid]["type"] = matched_type
                        break

            # Video weergaven
            vc = re.search(r'"video_view_count":(\d+)', block)
            if vc:
                posts[pid]["views"] = max(posts[pid]["views"], int(vc.group(1)))
            pc = re.search(r'"play_count":(\d+)', block)
            if pc:
                posts[pid]["views"] = max(posts[pid]["views"], int(pc.group(1)))

    # Stap 2: Vind feedback data via subscription_target_id
    for m in re.finditer(r'"subscription_target_id":"(\d+)"', text):
        pid = m.group(1)
        if pid not in posts:
            continue

        # Feedback blok: zoek in 5000 chars na de match
        end = min(len(text), m.end() + 5000)
        block = text[m.start():end]

        rc = re.search(r'"reaction_count":\{"count":(\d+)', block)
        if rc:
            posts[pid]["likes"] = max(posts[pid]["likes"], int(rc.group(1)))

        sc = re.search(r'"i18n_share_count":"(\d+)"', block)
        if sc:
            posts[pid]["shares"] = max(posts[pid]["shares"], int(sc.group(1)))

        cc = re.search(r'"i18n_comment_count":"(\d+)"', block)
        if cc:
            posts[pid]["comments"] = max(posts[pid]["comments"], int(cc.group(1)))

        # Comment count (alternatief formaat)
        cc2 = re.search(r'"comment_rendering_instance":\{"comments":\{"total_count":(\d+)\}', block)
        if cc2:
            posts[pid]["comments"] = max(posts[pid]["comments"], int(cc2.group(1)))

        # Reactie breakdown (leuk, geweldig, grappig, etc.)
        for tr in re.finditer(r'"localized_name":"([^"]+)"[^}]*?"reaction_count":(\d+)', block):
            posts[pid]["reactions"][tr.group(1).lower()] = int(tr.group(2))

        # Video weergaven in feedback blok
        vc = re.search(r'"video_view_count":(\d+)', block)
        if vc:
            posts[pid]["views"] = max(posts[pid]["views"], int(vc.group(1)))
        pc = re.search(r'"play_count":(\d+)', block)
        if pc:
            posts[pid]["views"] = max(posts[pid]["views"], int(pc.group(1)))

    # Stap 3: Video views via brede zoekactie (los van post_id blokken)
    for vc in re.finditer(r'"video_view_count":(\d+)', text):
        search_start = max(0, vc.start() - 15000)
        block = text[search_start:vc.start()]
        pid_matches = list(re.finditer(r'"post_id":"(\d+)"', block))
        if not pid_matches:
            continue
        pid = pid_matches[-1].group(1)
        if pid in posts:
            posts[pid]["views"] = max(posts[pid]["views"], int(vc.group(1)))

    # Stap 4: Vind post-teksten (langere "text" velden nabij een post_id)
    for m in re.finditer(r'"text":"((?:[^"\\]|\\.){30,})"', text):
        raw = m.group(1)

        # Zoek dichtstbijzijnde post_id VOOR deze text
        search_start = max(0, m.start() - 15000)
        block = text[search_start:m.start()]
        pid_matches = list(re.finditer(r'"post_id":"(\d+)"', block))
        if not pid_matches:
            continue

        pid = pid_matches[-1].group(1)
        if pid not in posts or posts[pid]["text"]:
            continue

        # Decode JSON unicode escapes (incl. emoji surrogate pairs)
        try:
            decoded = json.loads(f'"{raw}"')
        except (json.JSONDecodeError, ValueError):
            decoded = raw.replace("\\n", "\n").replace("\\/", "/")
        posts[pid]["text"] = decoded

    # Filter posts zonder datum en sorteer nieuwste eerst
    result = [p for p in posts.values() if p["date"]]
    result.sort(key=lambda p: p["date"], reverse=True)
    return result[:max_posts]


# ─── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)

    if "--login" in sys.argv:
        login()
        sys.exit(0)

    page_name = "PrinsPetfoods"
    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            page_name = arg
            break

    print(f"Scraping {page_name}...")
    result = scrape_fb_page_posts(page_name, max_posts=25, max_scrolls=10)

    print(f"\nPagina: {result['page_info']}")
    print(f"\n{len(result['posts'])} posts:\n")
    for i, post in enumerate(result["posts"], 1):
        text = (post["text"] or "(geen tekst)")[:80]
        # Verwijder surrogates
        text = text.encode("utf-8", errors="replace").decode("utf-8")
        date = post["date"][:10] if post["date"] else "?"
        reactions = ", ".join(f"{k}: {v}" for k, v in post["reactions"].items()) if post["reactions"] else ""
        print(f"  {i}. [{date}] {post['likes']} likes, "
              f"{post['comments']} reacties, {post['shares']} shares")
        if reactions:
            print(f"     Reacties: {reactions}")
        print(f"     {text}")
        print()
