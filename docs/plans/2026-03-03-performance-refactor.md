# Performance Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Maak alle pagina's van de Prins Social Tracker instant (<1s) door multi-page architectuur, lazy sync, caching en batch queries.

**Architecture:** Refactor van monolitisch `app.py` naar `st.navigation()` multi-page app. Sync wordt on-demand i.p.v. blocking bij page load. Alle DB queries gecached, follower queries gebatched, IG insights geparallelliseerd.

**Tech Stack:** Streamlit 1.54 (`st.navigation`, `st.Page`), `concurrent.futures.ThreadPoolExecutor`, `@st.cache_data`

---

## Context

- **Werkdirectory:** `/Users/administrator/Documents/GitHub/prins-social-tracker/`
- **Draait lokaal:** SQLite (`social_tracker.db`), niet Turso (lokale `.env` zonder Turso keys)
- **Hoofdbestand:** `app.py` (2048 regels) — bevat alle pagina's, sync, sidebar, utilities
- **Database:** `database.py` — Turso + SQLite fallback
- **Belangrijke functies die verplaatst/gewijzigd worden:**
  - `show_single_channel()` → roept sync + dashboard + posts table aan
  - `show_channel_dashboard()` → KPI cards + grafieken
  - `show_posts_table()` → editable data table
  - `show_benchmark()` → concurrenten vergelijking
  - `_show_ai_page()` → AI inzichten
  - `_show_remarks_page()` → opmerkingen
  - `show_upload_tab()` → CSV upload
  - `sync_posts_from_api()` → Meta Graph API sync (22+ HTTP calls)
  - `sync_follower_current()` → follower sync
  - `sync_tiktok_followers()` / `sync_tiktok_videos()` → TikTok sync

---

### Task 1: Add batch follower query to database.py

**Doel:** Vervang 12+ individuele `get_follower_count()` calls door 1 batch query.

**Files:**
- Modify: `database.py` (na `get_follower_previous_month`, ~regel 206)
- Test: `tests/test_database.py`

**Step 1: Write the failing test**

Add to `tests/test_database.py`:

```python
def test_get_follower_counts_batch(tmp_path):
    """get_follower_counts_batch returns dict of month→followers."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    # Insert test data
    save_follower_snapshot(db_path, "instagram", "prins", 1000, month="2026-01")
    save_follower_snapshot(db_path, "instagram", "prins", 1100, month="2026-02")
    save_follower_snapshot(db_path, "instagram", "prins", 1200, month="2026-03")

    result = get_follower_counts_batch(db_path, "instagram", "prins")
    assert result == {"2026-01": 1000, "2026-02": 1100, "2026-03": 1200}


def test_get_follower_counts_batch_empty(tmp_path):
    """get_follower_counts_batch returns empty dict when no data."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    result = get_follower_counts_batch(db_path, "instagram", "prins")
    assert result == {}
```

Note: `save_follower_snapshot` calls `get_follower_count.clear()` which needs streamlit cache. The test file likely already handles this — check existing test patterns first. If tests use `@patch` or mock st.cache, follow the same pattern.

**Step 2: Run test to verify it fails**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python -m pytest tests/test_database.py::test_get_follower_counts_batch -v`
Expected: FAIL — `get_follower_counts_batch` not defined

**Step 3: Implement `get_follower_counts_batch` in database.py**

Add after `get_follower_previous_month` (around line 206):

```python
@st.cache_data(ttl=300)
def get_follower_counts_batch(db_path: str, platform: str, page: str) -> dict[str, int]:
    """Haal alle follower snapshots op voor platform/page in 1 query.

    Returns dict: {"2026-01": 1000, "2026-02": 1100, ...}
    """
    sql = ("SELECT month, followers FROM follower_snapshots "
           "WHERE platform = ? AND page = ? ORDER BY month ASC")
    params = [platform, page]
    if _USE_TURSO:
        rows = _turso_execute(sql, params)
        return {r["month"]: int(r["followers"]) for r in rows if r.get("followers") is not None}
    else:
        conn = _connect(db_path)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return {r["month"]: r["followers"] for r in rows}
```

Also add `get_follower_counts_batch` to the exports (it will be imported in app.py later).

**Step 4: Run test to verify it passes**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python -m pytest tests/test_database.py::test_get_follower_counts_batch tests/test_database.py::test_get_follower_counts_batch_empty -v`
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/administrator/Documents/GitHub/prins-social-tracker
git add database.py tests/test_database.py
git commit -m "feat: add get_follower_counts_batch for single-query follower lookups"
```

---

### Task 2: Parallelize Instagram insights fetching

**Doel:** Verander de 10 sequentiële IG insights API calls naar parallel (~5s → ~0.5s).

**Files:**
- Modify: `app.py:589-611` (inside `sync_posts_from_api`)

**Step 1: Add ThreadPoolExecutor import at top of app.py**

Add to imports (around line 6):
```python
from concurrent.futures import ThreadPoolExecutor, as_completed
```

**Step 2: Refactor the IG insights loop**

Replace the sequential per-post insights loop in `sync_posts_from_api` (lines ~588-625). Currently each post does an individual `requests.get()` for insights. Refactor to:

```python
            # Fetch insights in parallel for all posts
            ig_data = resp.json().get("data", [])

            def _fetch_ig_insights(post):
                post_reach = 0
                post_impressions = 0
                post_id = post.get("id")
                if post_id:
                    try:
                        ins_resp = requests.get(
                            f"{FB_BASE_URL}/{post_id}/insights",
                            params={
                                "metric": "reach,views",
                                "access_token": token,
                            },
                            timeout=10,
                        )
                        ins_resp.raise_for_status()
                        for m in ins_resp.json().get("data", []):
                            val = m.get("values", [{}])[0].get("value", 0)
                            if m.get("name") == "reach":
                                post_reach = val
                            elif m.get("name") == "views":
                                post_impressions = val
                    except Exception:
                        pass
                return {
                    "date": post.get("timestamp", "").replace("+0000", ""),
                    "type": post.get("media_type", "Post"),
                    "text": (post.get("caption") or "")[:200],
                    "reach": post_reach,
                    "views": post_impressions,
                    "likes": post.get("like_count", 0),
                    "comments": post.get("comments_count", 0),
                    "shares": 0,
                    "clicks": 0,
                    "page": brand,
                    "source": "api",
                }

            with ThreadPoolExecutor(max_workers=5) as executor:
                ig_posts = list(executor.map(_fetch_ig_insights, ig_data))
```

This replaces the old `for post in resp.json()...` loop + the per-post insights `try/except` block (lines ~588-624).

**Step 3: Verify the app still runs**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python -c "from app import sync_posts_from_api; print('OK')"`
Expected: OK (no import errors)

**Step 4: Commit**

```bash
cd /Users/administrator/Documents/GitHub/prins-social-tracker
git add app.py
git commit -m "perf: parallelize Instagram insights fetching (10x → 2x faster sync)"
```

---

### Task 3: Use cached get_posts everywhere + pass data down

**Doel:** Elimineer dubbele ongecachte `get_posts()` calls in `show_channel_dashboard` en `show_posts_table`.

**Files:**
- Modify: `app.py` — functies `show_single_channel`, `show_channel_dashboard`, `show_posts_table`

**Step 1: Modify `show_single_channel` to fetch posts once and pass down**

In `show_single_channel` (line ~1335), fetch posts ONCE with the cached wrapper and pass to both functions:

```python
def show_single_channel(platform: str, page: str):
    """Show dashboard + posts for a single platform/page combination."""
    label = page.capitalize()
    plat_label = platform.capitalize()

    PLATFORM_ICONS = {
        "facebook": ":material/public:",
        "tiktok": ":material/music_note:",
        "instagram": ":material/photo_camera:",
    }
    icon = PLATFORM_ICONS.get(platform, "")

    st.header(f"{icon} {plat_label}")
    st.caption(f"{label} overzicht")

    # Fetch posts ONCE (cached) and pass to both sub-functions
    posts = _cached_get_posts(platform, page)
    show_channel_dashboard(platform, page, posts=posts)
    st.subheader("Posts")
    show_posts_table(platform, page, posts=posts)
```

Note: sync calls are REMOVED here — they move to a sync button in Task 5.

**Step 2: Add `posts` parameter to `show_channel_dashboard`**

Change signature from:
```python
def show_channel_dashboard(platform: str, page: str):
```
to:
```python
def show_channel_dashboard(platform: str, page: str, posts: list | None = None):
```

Replace `posts = get_posts(platform=platform, page=page)` (line 876) with:
```python
    if posts is None:
        posts = _cached_get_posts(platform, page)
```

**Step 3: Add `posts` parameter to `show_posts_table`**

Change signature from:
```python
def show_posts_table(platform: str, page: str):
```
to:
```python
def show_posts_table(platform: str, page: str, posts: list | None = None):
```

Replace `posts = get_posts(platform=platform, page=page)` (line 689) with:
```python
    if posts is None:
        posts = _cached_get_posts(platform, page)
```

**Step 4: Replace `_get_yearly_followers` with batch version**

Replace the nested function `_get_yearly_followers` (lines ~1030-1039) inside `show_channel_dashboard`:

```python
    @st.cache_data(ttl=900)
    def _get_yearly_followers(_platform, _page, _years):
        all_data = get_follower_counts_batch(DEFAULT_DB, _platform, _page)
        result = {}
        for year in sorted(_years):
            monthly = []
            for m in range(1, 13):
                monthly.append(all_data.get(f"{year}-{m:02d}"))
            result[year] = monthly
        return result
```

Add `get_follower_counts_batch` to the imports from `database` at the top of app.py.

**Step 5: Verify app runs**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && streamlit run app.py --server.headless true &` then open in browser, verify channel pages load and show data. Kill the process after.

**Step 6: Commit**

```bash
cd /Users/administrator/Documents/GitHub/prins-social-tracker
git add app.py
git commit -m "perf: cache get_posts calls, batch follower queries, pass data down"
```

---

### Task 4: Lazy sync — replace auto-sync with manual sync button

**Doel:** Pagina's laden altijd instant vanuit cache/DB. Sync is on-demand via een knop.

**Files:**
- Modify: `app.py` — `show_single_channel` (remove sync calls), add sync UI component

**Step 1: Create a reusable sync indicator + button component**

Add this function after the existing sync functions (~line 654):

```python
def _sync_status_bar(platform: str, page: str):
    """Toon laatst gesynct tijdstip + sync knop."""
    cache_key = f"_last_sync_{page}_{platform}"
    last_sync = st.session_state.get(cache_key)

    col_status, col_btn = st.columns([4, 1])
    with col_status:
        if last_sync:
            minutes_ago = (datetime.now(timezone.utc) - last_sync).total_seconds() / 60
            if minutes_ago < 1:
                st.caption(":material/check_circle: Zojuist gesynct")
            elif minutes_ago < 60:
                st.caption(f":material/schedule: Gesynct {int(minutes_ago)} min geleden")
            else:
                st.caption(f":material/schedule: Gesynct {int(minutes_ago / 60)}u geleden")
        else:
            st.caption(":material/info: Nog niet gesynct deze sessie")
    with col_btn:
        if st.button(":material/sync: Sync", key=f"sync_{page}_{platform}",
                      use_container_width=True):
            with st.spinner("Synchroniseren..."):
                if platform == "tiktok":
                    sync_tiktok_followers(page)
                    sync_tiktok_videos(page)
                else:
                    sync_posts_from_api(page)
                    sync_follower_current(page)
                # Clear post cache so new data shows up
                _cached_get_posts.clear()
                st.session_state[cache_key] = datetime.now(timezone.utc)
            st.rerun()
```

**Step 2: Use sync bar in `show_single_channel` instead of auto-sync**

The sync calls were already removed in Task 3 Step 1. Now add the sync bar. Update `show_single_channel`:

```python
def show_single_channel(platform: str, page: str):
    """Show dashboard + posts for a single platform/page combination."""
    label = page.capitalize()
    plat_label = platform.capitalize()

    PLATFORM_ICONS = {
        "facebook": ":material/public:",
        "tiktok": ":material/music_note:",
        "instagram": ":material/photo_camera:",
    }
    icon = PLATFORM_ICONS.get(platform, "")

    st.header(f"{icon} {plat_label}")
    st.caption(f"{label} overzicht")

    _sync_status_bar(platform, page)

    posts = _cached_get_posts(platform, page)
    show_channel_dashboard(platform, page, posts=posts)
    st.subheader("Posts")
    show_posts_table(platform, page, posts=posts)
```

**Step 3: Verify sync button works**

Run the app, navigate to a channel page. The page should load instantly from DB. Click "Sync" and verify new data is fetched.

**Step 4: Commit**

```bash
cd /Users/administrator/Documents/GitHub/prins-social-tracker
git add app.py
git commit -m "perf: lazy sync — replace blocking auto-sync with on-demand sync button"
```

---

### Task 5: Refactor to st.navigation multi-page architecture

**Doel:** Split `app.py` in aparte pages zodat alleen de actieve pagina's code draait.

**Files:**
- Modify: `app.py` — strip naar entrypoint + sidebar + shared utilities
- Create: `pages/channel.py`
- Create: `pages/benchmark.py`
- Create: `pages/ai_insights.py`
- Create: `pages/remarks.py`

**Important design note:** Met `st.navigation()` + `st.Page()` wordt alleen de geselecteerde pagina's `run()` uitgevoerd. Dit voorkomt dat alle pagina's hun data laden bij elke interactie.

De huidige sidebar-navigatie (session_state.nav + buttons) wordt vervangen door `st.navigation()` met `st.Page` objecten gegroepeerd in secties.

**Step 1: Create `pages/` directory**

```bash
mkdir -p /Users/administrator/Documents/GitHub/prins-social-tracker/pages
```

**Step 2: Create `pages/channel.py`**

This file renders a single channel (platform + page). It reads `st.session_state` to know which channel to show. It imports the relevant functions from `app.py`.

```python
"""Channel page — shows dashboard + posts for a single platform/page."""

import streamlit as st

from app import (
    _cached_get_posts,
    _sync_status_bar,
    show_channel_dashboard,
    show_posts_table,
)


def run(platform: str, page: str):
    label = page.capitalize()
    plat_label = platform.capitalize()

    PLATFORM_ICONS = {
        "facebook": ":material/public:",
        "tiktok": ":material/music_note:",
        "instagram": ":material/photo_camera:",
    }
    icon = PLATFORM_ICONS.get(platform, "")

    st.header(f"{icon} {plat_label}")
    st.caption(f"{label} overzicht")

    _sync_status_bar(platform, page)

    posts = _cached_get_posts(platform, page)
    show_channel_dashboard(platform, page, posts=posts)
    st.subheader("Posts")
    show_posts_table(platform, page, posts=posts)
```

**Step 3: Create `pages/benchmark.py`**

```python
"""Benchmark page — competitor comparison."""

import streamlit as st
from app import show_benchmark

show_benchmark()
```

**Step 4: Create `pages/ai_page.py`**

```python
"""AI Insights page."""

import streamlit as st
from app import _show_ai_page

_show_ai_page()
```

**Step 5: Create `pages/remarks.py`**

```python
"""Opmerkingen page."""

import streamlit as st
from app import _show_remarks_page

_show_remarks_page()
```

**Step 6: Refactor `main()` in app.py to use `st.navigation()`**

Replace the entire `main()` function (lines ~1829-1939) and the entrypoint block (lines ~2035-2048) with:

```python
def main():
    _auto_refresh_tokens()

    from functools import partial
    from pages.channel import run as channel_run

    # Build page list with st.Page using callables
    prins_pages = [
        st.Page(partial(channel_run, "instagram", "prins"),
                title="Instagram", icon=":material/photo_camera:",
                url_path="prins-instagram", default=True),
        st.Page(partial(channel_run, "facebook", "prins"),
                title="Facebook", icon=":material/public:",
                url_path="prins-facebook"),
        st.Page(partial(channel_run, "tiktok", "prins"),
                title="TikTok", icon=":material/music_note:",
                url_path="prins-tiktok"),
    ]
    edupet_pages = [
        st.Page(partial(channel_run, "instagram", "edupet"),
                title="Instagram", icon=":material/photo_camera:",
                url_path="edupet-instagram"),
        st.Page(partial(channel_run, "facebook", "edupet"),
                title="Facebook", icon=":material/public:",
                url_path="edupet-facebook"),
    ]
    other_pages = [
        st.Page("pages/benchmark.py",
                title="Concurrenten", icon=":material/leaderboard:",
                url_path="concurrenten"),
        st.Page("pages/ai_page.py",
                title="AI Inzichten", icon=":material/auto_awesome:",
                url_path="ai-inzichten"),
        st.Page("pages/remarks.py",
                title="Opmerkingen", icon=":material/comment:",
                url_path="opmerkingen"),
    ]

    pg = st.navigation({
        "Prins": prins_pages,
        "Edupet": edupet_pages,
        "Tools": other_pages,
    })

    # Sidebar extras — token status (keep existing code from lines 1888-1917)
    with st.sidebar:
        _cur_token = _get_secret("PRINS_TOKEN")
        _cur_valid = _check_token(_cur_token) if _cur_token else False
        if _cur_valid:
            _cur_user = _get_secret("USER_TOKEN")
            _days = _token_expiry_days(_cur_user) if _cur_user else None
            if _days is not None and _days < 10:
                st.warning(f"Token verloopt over {_days} dagen — wordt automatisch vernieuwd",
                           icon=":material/schedule:")
            elif _days is not None:
                st.success(f"API verbonden ({_days}d geldig)", icon=":material/check_circle:")
            else:
                st.success("API verbonden", icon=":material/check_circle:")
        else:
            st.error("Token verlopen", icon=":material/error:")
            new_token = st.text_input(
                "User Token",
                type="password",
                placeholder="Plak hier je nieuwe token",
            )
            if st.button("Vernieuwen", key="btn_refresh_token", use_container_width=True):
                if new_token:
                    success, msg = refresh_all_tokens(new_token)
                    if success:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Plak eerst een token.")

    _page_fade_in()
    pg.run()


# ── Entrypoint ──
_query_params = st.query_params
_page_param = _query_params.get("page", "")

if _page_param == "ping":
    st.write("pong")
    st.stop()
elif _page_param == "terms":
    show_terms_of_service()
elif _page_param == "privacy":
    show_privacy_policy()
else:
    main()
```

**Step 7: Remove old sidebar nav code**

Delete the old sidebar navigation (session_state.nav, set_nav, all the buttons) and the old if/elif nav routing block. Also remove `show_single_channel` since its logic is now in `pages/channel.py`.

**Step 8: Remove old `show_brand_page` function**

This function (line ~794) is not used in the current navigation. Delete it.

**Step 9: Try logo in sidebar**

Keep `st.logo("files/prins_logo.png")` in `main()` before `st.navigation()`.

**Step 10: Verify all pages work**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && streamlit run app.py`

Test each page:
- Prins Instagram / Facebook / TikTok
- Edupet Instagram / Facebook
- Concurrenten
- AI Inzichten
- Opmerkingen
- `?page=ping` health check
- `?page=terms` and `?page=privacy`

**Step 11: Commit**

```bash
cd /Users/administrator/Documents/GitHub/prins-social-tracker
git add app.py pages/
git commit -m "refactor: split into st.navigation multi-page architecture for instant page loads"
```

---

### Task 6: Also cache follower chart in dashboard overview

**Doel:** De `overview_follower_chart` in `show_dashboard` doet per-maand follower queries. Vervang door batch.

**Files:**
- Modify: `app.py` — `show_dashboard` functie (~regel 1296-1332)

**Step 1: Replace per-month follower lookups with batch**

In `overview_follower_chart()` (inside `show_dashboard`), replace the loop:

```python
for m in range(1, 13):
    month_str = f"{sorted_yrs[-1]}-{m:02d}"
    fc = get_follower_count(DEFAULT_DB, plat, page or "prins", month_str)
    values.append(fc)
```

With:
```python
all_followers = get_follower_counts_batch(DEFAULT_DB, plat, page or "prins")
values = [all_followers.get(f"{sorted_yrs[-1]}-{m:02d}") for m in range(1, 13)]
```

**Step 2: Verify dashboard chart still works**

Run app, check that the follower growth chart on the dashboard page renders correctly.

**Step 3: Commit**

```bash
cd /Users/administrator/Documents/GitHub/prins-social-tracker
git add app.py
git commit -m "perf: batch follower queries in dashboard overview chart"
```

---

### Task 7: Final verification and cleanup

**Files:**
- Modify: `app.py` — remove any dead code

**Step 1: Remove unused imports and dead functions**

Check for:
- `show_single_channel` (replaced by `pages/channel.py:run`)
- `show_brand_page` (unused)
- Any unused imports

**Step 2: Run all existing tests**

Run: `cd /Users/administrator/Documents/GitHub/prins-social-tracker && python -m pytest tests/ -v`
Expected: All tests pass

**Step 3: Run the full app and test all pages**

Verify:
- [ ] Prins Instagram loads instantly
- [ ] Prins Facebook loads instantly
- [ ] Prins TikTok loads instantly
- [ ] Edupet Instagram loads instantly
- [ ] Edupet Facebook loads instantly
- [ ] Concurrenten page loads and shows data
- [ ] AI Inzichten page loads
- [ ] Opmerkingen page loads
- [ ] Sync button works on channel pages
- [ ] Navigation works — switching pages is instant
- [ ] Token status shows in sidebar
- [ ] `?page=ping` returns pong
- [ ] CSV upload still works (if applicable in sidebar/pages)

**Step 4: Commit**

```bash
cd /Users/administrator/Documents/GitHub/prins-social-tracker
git add -A
git commit -m "chore: cleanup dead code after performance refactor"
```
