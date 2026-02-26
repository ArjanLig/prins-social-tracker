# app.py  v2.1
"""Prins Social Tracker — Streamlit Dashboard."""

import os
import tempfile
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from csv_import import detect_platform, parse_csv_file
from tiktok_api import (
    tiktok_get_user_info,
    tiktok_get_videos,
)
from database import (
    DEFAULT_DB,
    add_remark,
    get_follower_count,
    get_follower_previous_month,
    get_monthly_stats,
    get_posts,
    get_remarks,
    get_report,
    get_uploads,
    init_db,
    insert_posts,
    log_upload,
    save_follower_snapshot,
    save_report,
    update_post_labels,
    update_remark_status,
)
import ai_insights


def _get_secret(key: str, default: str = "") -> str:
    """Haal waarde op uit st.secrets (Streamlit Cloud) of os.getenv (lokaal)."""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.getenv(key, default)


st.set_page_config(
    page_title="Prins Social Tracker",
    page_icon=":material/analytics:",
    layout="wide",
)


# Init database on startup (only once per app deployment)
@st.cache_resource
def _init_db_once():
    init_db()
    return True

_init_db_once()


def _page_fade_in():
    """Hide stale content (white flash) and fade in new content."""
    st.html("""<style>
/* Hide ALL Streamlit running/status indicators */
[data-testid="stStatusWidget"],
[data-testid="stRunningStatus"],
.stStatusWidget,
header ~ div:has(> [data-testid="stStatusWidget"]) {
    display: none !important;
    visibility: hidden !important;
}
/* White-out during rerun: hide everything in the main content area */
.stApp[data-test-script-state="running"] .stMainBlockContainer {
    opacity: 0 !important;
}
/* Apple-style centered spinner during rerun */
@keyframes appleSpinner { to { transform: rotate(360deg); } }
.stApp[data-test-script-state="running"]::after {
    content: "";
    position: fixed;
    top: 50%; left: 50%;
    width: 28px; height: 28px;
    margin: -14px 0 0 -14px;
    border: 3px solid #e0e0e0;
    border-top-color: #0d5a4d;
    border-radius: 50%;
    animation: appleSpinner 0.7s linear infinite;
    z-index: 9999;
}
/* Fade in new content */
@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}
.stMainBlockContainer [data-testid="stVerticalBlockBorderWrapper"] {
    animation: fadeIn 0.3s ease-out both;
}
.stMainBlockContainer [data-testid="stVerticalBlockBorderWrapper"]:nth-child(2) { animation-delay: 0.04s; }
.stMainBlockContainer [data-testid="stVerticalBlockBorderWrapper"]:nth-child(3) { animation-delay: 0.08s; }
.stMainBlockContainer [data-testid="stVerticalBlockBorderWrapper"]:nth-child(4) { animation-delay: 0.12s; }
.stMainBlockContainer [data-testid="stVerticalBlockBorderWrapper"]:nth-child(5) { animation-delay: 0.16s; }
.stMainBlockContainer [data-testid="stVerticalBlockBorderWrapper"]:nth-child(n+6) { animation-delay: 0.20s; }
</style>""")


# ── Meta Graph API ──
FB_API_VERSION = "v22.0"
FB_BASE_URL = f"https://graph.facebook.com/{FB_API_VERSION}"
META_APP_ID = _get_secret("META_APP_ID")
META_APP_SECRET = _get_secret("META_APP_SECRET")

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

# ── TikTok (scraper, geen tokens nodig) ──
TIKTOK_USERNAME = "prinspetfoods"


@st.cache_data(ttl=900)
def _check_token(token: str) -> bool:
    """Check of een token nog geldig is (cached 15 min)."""
    if not token:
        return False
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=10,
        )
        data = resp.json().get("data", {})
        return data.get("is_valid", False)
    except Exception:
        # Als de check zelf faalt (netwerk etc.), neem aan dat token geldig is
        # zodat de app niet onnodig "verlopen" toont
        return True


def _exchange_for_long_lived(short_token: str) -> str | None:
    """Wissel een short-lived user token in voor een long-lived token."""
    if not META_APP_ID or not META_APP_SECRET:
        return None
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": META_APP_ID,
                "client_secret": META_APP_SECRET,
                "fb_exchange_token": short_token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception:
        return None


def _get_permanent_page_tokens(user_token: str) -> dict:
    """Haal permanente page tokens op via me/accounts.

    Returns dict: {page_id: {"token": ..., "name": ...}}
    """
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/me/accounts",
            params={"access_token": user_token,
                    "fields": "id,name,access_token"},
            timeout=10,
        )
        resp.raise_for_status()
        pages = {}
        for page in resp.json().get("data", []):
            pages[page["id"]] = {
                "token": page["access_token"],
                "name": page.get("name", ""),
            }
        return pages
    except Exception:
        return {}


def _update_env(key: str, value: str):
    """Update of voeg een key toe in het .env bestand."""
    lines = []
    found = False
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    with open(ENV_PATH, "w") as f:
        f.writelines(lines)


def refresh_all_tokens(user_token: str) -> tuple[bool, str]:
    """Vernieuw alle tokens vanuit een user token.

    1. Wissel in voor long-lived token
    2. Haal permanente page tokens op
    3. Sla op in .env
    Returns (success, message)
    """
    # Stap 1: long-lived token
    long_lived = _exchange_for_long_lived(user_token)
    if not long_lived:
        long_lived = user_token

    # Stap 2: page tokens ophalen (met long-lived voor permanente tokens)
    pages = _get_permanent_page_tokens(long_lived)
    if not pages:
        # Fallback: probeer met originele token
        pages = _get_permanent_page_tokens(user_token)
    if not pages:
        return False, "Kon geen page tokens ophalen. Controleer of het token de juiste permissies heeft."

    # Stap 3: opslaan in .env
    _update_env("USER_TOKEN", long_lived)

    prins_page_id = _get_secret("PRINS_PAGE_ID")
    edupet_page_id = _get_secret("EDUPET_PAGE_ID")
    updated = []

    if prins_page_id in pages:
        _update_env("PRINS_TOKEN", pages[prins_page_id]["token"])
        updated.append(f"Prins ({pages[prins_page_id]['name']})")
    if edupet_page_id in pages:
        _update_env("EDUPET_TOKEN", pages[edupet_page_id]["token"])
        updated.append(f"Edupet ({pages[edupet_page_id]['name']})")

    if not updated:
        return False, f"Page ID's niet gevonden. Beschikbare pages: {', '.join(p['name'] for p in pages.values())}"

    return True, f"Tokens vernieuwd voor: {', '.join(updated)}"


# ── Auto token refresh bij opstarten ──
_prins_token = _get_secret("PRINS_TOKEN")
_tokens_valid = _check_token(_prins_token) if _prins_token else False

if not _tokens_valid:
    # Probeer automatisch te vernieuwen via user token
    _user_token = _get_secret("USER_TOKEN")
    if _user_token and META_APP_ID and META_APP_SECRET:
        _success, _msg = refresh_all_tokens(_user_token)
        if _success:
            # Herlaad de vernieuwde tokens uit .env
            load_dotenv(override=True)
            _prins_token = _get_secret("PRINS_TOKEN")
            _tokens_valid = _check_token(_prins_token) if _prins_token else False

BRAND_CONFIG = {
    "prins": {
        "token": _get_secret("PRINS_TOKEN"),
        "page_id": _get_secret("PRINS_PAGE_ID"),
    },
    "edupet": {
        "token": _get_secret("EDUPET_TOKEN"),
        "page_id": _get_secret("EDUPET_PAGE_ID"),
    },
}


@st.cache_data(ttl=900)
def sync_follower_current(brand: str) -> dict:
    """Snelle sync: haal alleen huidige volgers op (2-3 API calls)."""
    config = BRAND_CONFIG.get(brand)
    if not config:
        return {}

    token = config.get("token")
    page_id = config.get("page_id")
    if not token or not page_id:
        return {}

    result = {}
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    from datetime import timedelta

    # Facebook: huidige volgers + vorige maand via page_follows
    try:
        since = (datetime.now(timezone.utc).replace(day=1) - timedelta(days=1)).replace(day=1)
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}/insights",
            params={
                "metric": "page_follows",
                "period": "day",
                "since": since.strftime("%Y-%m-%d"),
                "until": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "access_token": token,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            values = resp.json().get("data", [{}])[0].get("values", [])
            monthly = {}
            for v in values:
                month_key = v.get("end_time", "")[:7]
                monthly[month_key] = v.get("value", 0)
            for month_key, followers in monthly.items():
                save_follower_snapshot(DEFAULT_DB, "facebook", brand,
                                      followers, month=month_key)
            result["facebook"] = monthly.get(current_month)
    except Exception:
        pass

    # Instagram: huidige volgers + dagelijkse delta's
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}",
            params={"fields": "instagram_business_account{followers_count}",
                    "access_token": token},
            timeout=15,
        )
        ig_data = resp.json().get("instagram_business_account", {})
        ig_id = ig_data.get("id")
        current_followers = ig_data.get("followers_count", 0)
        if ig_id and current_followers:
            save_follower_snapshot(DEFAULT_DB, "instagram", brand,
                                  current_followers, month=current_month)
            result["instagram"] = current_followers

            # Dagelijkse delta's voor vorige maand berekening
            resp3 = requests.get(
                f"{FB_BASE_URL}/{ig_id}/insights",
                params={"metric": "follower_count", "period": "day",
                        "access_token": token},
                timeout=15,
            )
            if resp3.status_code == 200:
                values = resp3.json().get("data", [{}])[0].get("values", [])
                monthly_delta = {}
                for v in values:
                    month_key = v.get("end_time", "")[:7]
                    monthly_delta[month_key] = monthly_delta.get(month_key, 0) + v.get("value", 0)
                running = current_followers
                for month_key in sorted(monthly_delta.keys(), reverse=True):
                    if month_key == current_month:
                        running -= monthly_delta[month_key]
                        continue
                    save_follower_snapshot(DEFAULT_DB, "instagram", brand,
                                          running, month=month_key)
    except Exception:
        pass

    return result


@st.cache_data(ttl=900)
def sync_posts_from_api(brand: str) -> dict:
    """Haal recente posts op via de Graph API en sla ze op in de database."""
    config = BRAND_CONFIG.get(brand)
    if not config:
        return {"facebook": 0, "instagram": 0}

    token = config.get("token")
    page_id = config.get("page_id")
    if not token or not page_id:
        return {"facebook": 0, "instagram": 0}

    result = {"facebook": 0, "instagram": 0}

    # Facebook posts (laatste 10 — historische data zit al in DB)
    # post_media_view vervangt post_impressions sinds v22.0
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}/published_posts",
            params={
                "fields": "message,created_time,shares,"
                          "likes.summary(true),comments.summary(true),"
                          "insights.metric(post_media_view,post_clicks)",
                "limit": 10,
                "access_token": token,
            },
            timeout=15,
        )
        resp.raise_for_status()
        fb_posts = []
        for post in resp.json().get("data", []):
            likes = post.get("likes", {}).get("summary", {}).get("total_count", 0)
            comments = post.get("comments", {}).get("summary", {}).get("total_count", 0)
            shares = post.get("shares", {}).get("count", 0)
            clicks = 0
            views = 0
            for insight in post.get("insights", {}).get("data", []):
                val = insight.get("values", [{}])[0].get("value", 0)
                if insight.get("name") == "post_clicks":
                    clicks = val
                elif insight.get("name") == "post_media_view":
                    views = val
            fb_posts.append({
                "date": post.get("created_time", "").replace("+0000", ""),
                "type": "Post",
                "text": (post.get("message") or "")[:200],
                "reach": 0,
                "views": views,
                "likes": likes,
                "comments": comments,
                "shares": shares,
                "clicks": clicks,
                "page": brand,
                "source": "api",
            })
        if fb_posts:
            result["facebook"] = insert_posts(DEFAULT_DB, fb_posts, "facebook")
    except Exception:
        pass

    # Instagram posts (laatste 10)
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}",
            params={"fields": "instagram_business_account",
                    "access_token": token},
            timeout=10,
        )
        resp.raise_for_status()
        ig_id = resp.json().get("instagram_business_account", {}).get("id")
        if ig_id:
            resp = requests.get(
                f"{FB_BASE_URL}/{ig_id}/media",
                params={
                    "fields": "caption,timestamp,like_count,comments_count,"
                              "media_type",
                    "limit": 10,
                    "access_token": token,
                },
                timeout=10,
            )
            resp.raise_for_status()
            ig_posts = []
            for post in resp.json().get("data", []):
                # Fetch insights per post for reach & impressions
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
                ig_posts.append({
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
                })
            if ig_posts:
                result["instagram"] = insert_posts(DEFAULT_DB, ig_posts, "instagram")
    except Exception:
        pass

    return result


@st.cache_data(ttl=900)
def sync_tiktok_followers(brand: str) -> int | None:
    """Sync TikTok volgers voor een merk via scraper (gecached 15 min)."""
    user_info = tiktok_get_user_info(TIKTOK_USERNAME)
    if user_info and "follower_count" in user_info:
        count = user_info["follower_count"]
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        save_follower_snapshot(DEFAULT_DB, "tiktok", brand, count, month=current_month)
        return count
    return None


@st.cache_data(ttl=900)
def sync_tiktok_videos(brand: str) -> int:
    """Sync recente TikTok video's via scraper (gecached 15 min)."""
    videos = tiktok_get_videos(TIKTOK_USERNAME)
    if videos:
        return insert_posts(DEFAULT_DB, videos, "tiktok")
    return 0



MAAND_NL = {
    1: "Januari", 2: "Februari", 3: "Maart", 4: "April",
    5: "Mei", 6: "Juni", 7: "Juli", 8: "Augustus",
    9: "September", 10: "Oktober", 11: "November", 12: "December",
}


def check_password_DISABLED() -> bool:
    """Simple password gate (currently disabled)."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.title("Prins Social Tracker")
        st.caption("Social media dashboard")
        password = st.text_input("Wachtwoord", type="password")
        if st.button("Inloggen", use_container_width=True):
            if password == st.secrets.get("password", ""):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Onjuist wachtwoord")
    return False


def show_posts_table(platform: str, page: str):
    """Render an editable posts table grouped by year > month in expanders."""
    key_prefix = f"{page}_{platform}"
    posts = get_posts(platform=platform, page=page)
    if not posts:
        st.info(f"Nog geen {platform} posts. Upload een CSV via 'CSV Upload'.")
        return

    df = pd.DataFrame(posts)
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")
    df["datum_fmt"] = df["date_parsed"].dt.strftime("%d-%m-%Y")
    df["tijd_fmt"] = df["date_parsed"].dt.strftime("%H:%M")
    df["year"] = df["date_parsed"].dt.year
    df["month_num"] = df["date_parsed"].dt.month
    df = df.sort_values("date_parsed", ascending=False)

    if platform == "tiktok":
        display_cols = ["datum_fmt", "tijd_fmt", "type", "text", "impressions", "likes",
                        "comments", "shares", "engagement",
                        "engagement_rate", "theme", "campaign"]
    elif platform == "instagram":
        display_cols = ["datum_fmt", "tijd_fmt", "type", "text", "reach", "impressions", "likes",
                        "comments", "shares", "engagement",
                        "engagement_rate", "theme", "campaign"]
    else:
        display_cols = ["datum_fmt", "tijd_fmt", "type", "text", "reach", "impressions", "likes",
                        "comments", "shares", "clicks", "engagement",
                        "engagement_rate", "theme", "campaign"]
    col_labels = {
        "datum_fmt": "Datum", "tijd_fmt": "Tijd", "type": "Type", "text": "Omschrijving",
        "reach": "Bereik", "impressions": "Weergaven", "likes": "Likes",
        "comments": "Reacties", "shares": "Shares", "clicks": "Klikken",
        "engagement": "Engagement", "engagement_rate": "ER%",
        "theme": "Thema", "campaign": "Campagne",
    }

    # Column config for polished data display
    _col_config = {
        "id": None,  # Hide internal ID
        "Datum": st.column_config.TextColumn("Datum", width="small"),
        "Tijd": st.column_config.TextColumn("Tijd", width="small"),
        "Type": st.column_config.TextColumn("Type", width="small"),
        "Omschrijving": st.column_config.TextColumn("Omschrijving", width="large"),
        "Bereik": st.column_config.NumberColumn("Bereik", format="%d"),
        "Weergaven": st.column_config.NumberColumn("Weergaven", format="%d"),
        "Likes": st.column_config.NumberColumn("Likes", format="%d"),
        "Reacties": st.column_config.NumberColumn("Reacties", format="%d"),
        "Shares": st.column_config.NumberColumn("Shares", format="%d"),
        "Klikken": st.column_config.NumberColumn("Klikken", format="%d"),
        "Engagement": st.column_config.NumberColumn("Engagement", format="%d"),
        "ER%": st.column_config.NumberColumn("ER%",
                                                format="%.1f%%"),
        "Thema": st.column_config.TextColumn("Thema", width="medium"),
        "Campagne": st.column_config.TextColumn("Campagne", width="medium"),
    }

    years = sorted(df["year"].dropna().unique(), reverse=True)
    for year in years:
        year_df = df[df["year"] == year]
        year_int = int(year)
        with st.expander(f":material/calendar_month: {year_int}", expanded=(year == years[0])):
            months = sorted(year_df["month_num"].dropna().unique())
            for month in months:
                month_df = year_df[year_df["month_num"] == month]
                month_name = MAAND_NL.get(int(month), str(int(month)))

                # Month summary metrics
                n_posts = len(month_df)
                total_eng = int(month_df["engagement"].sum())
                if platform == "tiktok":
                    avg_metric = month_df["impressions"].mean()
                    avg_label = "gem. views"
                else:
                    avg_metric = month_df["reach"].mean()
                    avg_label = "gem. bereik"
                avg_val = f"{avg_metric:,.0f}" if pd.notna(avg_metric) else "0"

                st.caption(f"**{month_name}** — {n_posts} posts  |  {total_eng:,} engagement  |  {avg_val} {avg_label}")

                display_df = month_df[["id"] + display_cols].copy()
                display_df = display_df.rename(columns=col_labels)

                editor_key = f"{key_prefix}_{year_int}_{int(month)}_editor"
                edited = st.data_editor(
                    display_df,
                    column_config=_col_config,
                    disabled=[c for c in display_df.columns
                              if c not in ("Thema", "Campagne")],
                    hide_index=True,
                    use_container_width=True,
                    key=editor_key,
                )

                # Save changes
                if not edited.equals(display_df):
                    save_key = f"{key_prefix}_{year_int}_{int(month)}_save"
                    if st.button(":material/save: Wijzigingen opslaan", key=save_key):
                        for idx in range(len(edited)):
                            row = edited.iloc[idx]
                            orig_row = display_df.iloc[idx] if idx < len(display_df) else None
                            if orig_row is not None:
                                if row["Thema"] != orig_row["Thema"] or row["Campagne"] != orig_row["Campagne"]:
                                    theme_val = row["Thema"] if pd.notna(row["Thema"]) else ""
                                    campaign_val = row["Campagne"] if pd.notna(row["Campagne"]) else ""
                                    update_post_labels(DEFAULT_DB, int(row["id"]), theme_val, campaign_val)
                        st.success("Labels opgeslagen!")


def show_brand_page(page: str):
    """Show Facebook + Instagram with separate dashboards per channel."""
    label = page.capitalize()
    st.header(label)
    st.caption("Facebook & Instagram overzicht")

    tab_fb, tab_ig = st.tabs([":material/public: Facebook", ":material/photo_camera: Instagram"])

    with tab_fb:
        st.subheader(f"{label} — Facebook")
        show_channel_dashboard("facebook", page)
        st.subheader("Posts")
        show_posts_table("facebook", page)

    with tab_ig:
        st.subheader(f"{label} — Instagram")
        show_channel_dashboard("instagram", page)
        st.subheader("Posts")
        show_posts_table("instagram", page)


def show_upload_tab():
    """CSV Upload tab."""
    st.header("CSV Upload")
    st.write("Upload CSV-exports uit Meta Business Suite. "
             "Platform (Facebook/Instagram) en merk (Prins/Edupet) "
             "worden automatisch gedetecteerd.")

    uploaded_files = st.file_uploader(
        "Kies CSV-bestanden", type=["csv"], accept_multiple_files=True
    )

    if uploaded_files and st.button("Importeren"):
        total_new = 0
        for uf in uploaded_files:
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                tmp.write(uf.getvalue())
                tmp_path = tmp.name
            try:
                platform = detect_platform(tmp_path)
                posts = parse_csv_file(tmp_path)
                if posts:
                    # Tel per merk hoeveel posts er zijn
                    from collections import Counter
                    page_counts = Counter(p.get("page") for p in posts)
                    count = insert_posts(DEFAULT_DB, posts, platform=platform)
                    total_new += count
                    # Log per merk
                    for pg, pg_cnt in page_counts.items():
                        if pg:
                            log_upload(DEFAULT_DB, uf.name, platform, pg, pg_cnt)
                    # Toon resultaat
                    brands = [f"{pg.capitalize()} ({c})"
                              for pg, c in page_counts.items() if pg]
                    skipped = page_counts.get(None, 0)
                    msg = f"✓ {uf.name}: {count} nieuwe {platform} posts — {', '.join(brands)}"
                    if skipped:
                        msg += f" ({skipped} overgeslagen, onbekend account)"
                    st.success(msg)
                else:
                    st.warning(f"⚠ {uf.name}: geen posts gevonden")
            finally:
                os.unlink(tmp_path)

        if total_new > 0:
            st.balloons()

    # Upload history
    uploads = get_uploads()
    if uploads:
        st.subheader("Upload geschiedenis")
        st.dataframe(
            [{"Bestand": u["filename"], "Platform": u["platform"],
              "Pagina": u["page"], "Posts": u["post_count"],
              "Datum": u["uploaded_at"][:16].replace("T", " ")} for u in uploads],
            use_container_width=True,
        )


def show_channel_dashboard(platform: str, page: str):
    """Dashboard for a specific platform + page (e.g. Prins Facebook)."""
    label = f"{page.capitalize()} {platform.capitalize()}"
    posts = get_posts(platform=platform, page=page)

    if not posts:
        st.info(f"Nog geen {platform} data voor {page.capitalize()}.")
        return

    df_all = pd.DataFrame(posts)
    df_all["date_parsed"] = pd.to_datetime(df_all["date"], errors="coerce")

    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    df_month = df_all[df_all["date_parsed"].dt.strftime("%Y-%m") == current_month]

    # KPI cards — volgers uit database (al gesynchroniseerd door sync_follower_current)
    current_month = now.strftime("%Y-%m")
    follower_count = get_follower_count(DEFAULT_DB, platform, page, current_month)

    follower_delta = None
    if follower_count is not None:
        prev = get_follower_previous_month(DEFAULT_DB, platform, page)
        if prev is not None:
            follower_delta = follower_count - prev

    col1, col2, col3, col4, col5 = st.columns(5)
    if follower_count is not None:
        if follower_delta is not None:
            col1.metric("Volgers", f"{follower_count:,}",
                         delta=f"{follower_delta:+,} deze maand")
        else:
            col1.metric("Volgers", f"{follower_count:,}")
    else:
        col1.metric("Volgers", "–")
    posts_this_month = len(df_month)
    df_prev_months = df_all[df_all["date_parsed"].dt.strftime("%Y-%m") != current_month]
    prev_monthly_counts = df_prev_months.groupby(df_prev_months["date_parsed"].dt.strftime("%Y-%m")).size()
    posts_delta_str = None
    if len(prev_monthly_counts) > 0:
        avg_posts = prev_monthly_counts.mean()
        diff = posts_this_month - avg_posts
        posts_delta_str = f"{diff:+.0f} vs. gem."
    col2.metric("Posts deze maand", posts_this_month, delta=posts_delta_str)
    impressions_per_post = df_month['impressions'].mean() if len(df_month) > 0 else 0
    impressions_delta_str = None
    if len(df_prev_months) > 0:
        prev_imp_per_post = df_prev_months.groupby(
            df_prev_months["date_parsed"].dt.strftime("%Y-%m")
        )['impressions'].mean()
        if len(prev_imp_per_post) > 0:
            avg_imp = prev_imp_per_post.mean()
            diff = impressions_per_post - avg_imp
            impressions_delta_str = f"{diff:+,.0f} vs. gem."
    col3.metric("Gem. weergaven/post",
                f"{impressions_per_post:,.0f}" if pd.notna(impressions_per_post) else "0",
                delta=impressions_delta_str)
    if platform == "tiktok":
        total_shares = int(df_month['shares'].sum()) if len(df_month) > 0 else 0
        shares_delta_str = None
        if len(df_prev_months) > 0:
            prev_monthly_shares = df_prev_months.groupby(
                df_prev_months["date_parsed"].dt.strftime("%Y-%m")
            )['shares'].sum()
            if len(prev_monthly_shares) > 0:
                avg_shares = prev_monthly_shares.mean()
                diff = total_shares - avg_shares
                shares_delta_str = f"{diff:+,.0f} vs. gem."
        col4.metric("Shares deze maand", f"{total_shares:,}", delta=shares_delta_str)
    else:
        reach_per_post = df_month['reach'].mean() if len(df_month) > 0 else 0
        reach_delta_str = None
        if len(df_prev_months) > 0:
            prev_reach_per_post = df_prev_months.groupby(
                df_prev_months["date_parsed"].dt.strftime("%Y-%m")
            )['reach'].mean()
            if len(prev_reach_per_post) > 0:
                avg_reach = prev_reach_per_post.mean()
                diff = reach_per_post - avg_reach
                reach_delta_str = f"{diff:+,.0f} vs. gem."
        col4.metric("Gem. bereik/post",
                    f"{reach_per_post:,.0f}" if pd.notna(reach_per_post) else "0",
                    delta=reach_delta_str)

    # Engagement Rate deze maand vs. langlopend gemiddelde
    er_current = None
    er_avg = None
    if len(df_month) > 0 and follower_count and follower_count > 0:
        er_current = (df_month['engagement'].sum() / len(df_month)) / follower_count * 100

        df_prev = df_all[df_all["date_parsed"].dt.strftime("%Y-%m") != current_month]
        if len(df_prev) > 0:
            prev_months = df_prev.groupby(df_prev["date_parsed"].dt.strftime("%Y-%m"))
            monthly_ers = []
            for _, grp in prev_months:
                monthly_ers.append((grp['engagement'].sum() / len(grp)) / follower_count * 100)
            if monthly_ers:
                er_avg = sum(monthly_ers) / len(monthly_ers)

    if er_current is not None:
        er_delta_str = None
        if er_avg is not None:
            diff = er_current - er_avg
            er_delta_str = f"{diff:+.2f}% vs. gem."
        col5.metric("Engagement Rate", f"{er_current:.2f}%", delta=er_delta_str,
                    help="Engagement Rate = gemiddelde (likes + reacties + shares) per post, gedeeld door het aantal volgers × 100%.")
    else:
        col5.metric("Engagement Rate", "–",
                    help="Engagement Rate = gemiddelde (likes + reacties + shares) per post, gedeeld door het aantal volgers × 100%.")

    # Monthly trend line charts per jaar
    df_all["year"] = df_all["date_parsed"].dt.year
    df_all["month_num"] = df_all["date_parsed"].dt.month

    available_years = sorted(df_all["year"].dropna().unique().astype(int), reverse=True)
    if not available_years:
        return

    key_prefix = f"{page}_{platform}"
    MONTH_LABELS = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
                    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]
    # Fixed year-to-color mapping so 2026 is always the same color across platforms
    YEAR_COLOR_MAP = {2024: "#0d5a4d", 2025: "#81b29a", 2026: "#d32f2f",
                      2027: "#3d405b", 2028: "#f2cc8f"}
    YEAR_COLOR_DEFAULT = "#86868b"

    selected_years = st.multiselect(
        "Jaren vergelijken",
        options=available_years,
        default=available_years,
        key=f"{key_prefix}_allyears",
    )
    if not selected_years:
        return

    # Bouw maanddata per jaar
    yearly_data = {}
    for year in sorted(selected_years):
        df_year = df_all[df_all["year"] == year]
        by_month = df_year.groupby("month_num").agg(
            posts=("id", "count"),
            engagement=("engagement", "sum"),
            bereik=("reach", "sum"),
            weergaven=("impressions", "sum"),
            likes=("likes", "sum"),
            reacties=("comments", "sum"),
            er=("engagement_rate", "mean"),
        )
        by_month = by_month.reindex(range(1, 13))
        # Bereik per post (hoe ver komt je content)
        by_month["bereik_per_post"] = (by_month["bereik"] / by_month["posts"]).round(0)
        yearly_data[year] = by_month

    # Volgers-groei per maand uit follower_snapshots
    yearly_followers = {}
    for year in sorted(selected_years):
        monthly_followers = []
        for m in range(1, 13):
            month_str = f"{year}-{m:02d}"
            fc = get_follower_count(DEFAULT_DB, platform, page, month_str)
            monthly_followers.append(fc)
        yearly_followers[year] = monthly_followers

    layout_base = dict(
        font=dict(family="Inter, sans-serif", color="#1d1d1f"),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=10, b=40),
        xaxis=dict(
            gridcolor="#f0f0f2", title=None,
            tickvals=list(range(1, 13)), ticktext=MONTH_LABELS,
            tickfont=dict(color="#86868b", size=11),
            showline=False,
        ),
        yaxis=dict(
            gridcolor="#f0f0f2", title=None,
            tickfont=dict(color="#86868b", size=11),
            showline=False, zeroline=False,
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1,
                    font=dict(size=12, color="#1d1d1f")),
        hoverlabel=dict(
            bgcolor="white", bordercolor="#e0e0e0",
            font=dict(family="Inter, sans-serif", size=13, color="#1d1d1f"),
        ),
        hovermode="x unified",
    )

    def _hex_to_rgba(hex_color, alpha):
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    def year_line_chart(metric, title):
        fig = go.Figure()
        hover_fmt = "%{text}: %{y:.2f}%%<extra></extra>" if metric == "er" else "%{text}: %{y:,.0f}<extra></extra>"
        sorted_years = sorted(selected_years)
        for i, year in enumerate(sorted_years):
            color = YEAR_COLOR_MAP.get(year, YEAR_COLOR_DEFAULT)
            values = yearly_data[year][metric]
            # Area fill: strongest for most recent year, lighter for older
            is_latest = (year == sorted_years[-1])
            fill_alpha = 0.15 if is_latest else 0.06
            fig.add_trace(go.Scatter(
                x=list(range(1, 13)), y=values,
                name=str(year),
                mode="lines+markers",
                line=dict(color=color, width=2.5, shape="spline"),
                marker=dict(color="white", size=7,
                            line=dict(color=color, width=2)),
                fill="tozeroy",
                fillcolor=_hex_to_rgba(color, fill_alpha),
                hovertemplate=hover_fmt,
                text=[f"{MONTH_LABELS[m-1]} {year}" for m in range(1, 13)],
                connectgaps=True,
            ))
        fig.update_layout(**layout_base)
        return fig

    if platform == "tiktok":
        st.subheader("Video weergaven")
        st.plotly_chart(year_line_chart("weergaven", "Video weergaven"),
                        use_container_width=True)
    else:
        st.subheader("Organisch bereik")
        st.plotly_chart(year_line_chart("bereik", "Organisch bereik"),
                        use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("E.R. per post")
        st.plotly_chart(year_line_chart("er", "E.R. per post (gem. per maand)"),
                        use_container_width=True)
    with col_b:
        st.subheader("Bereik per post")
        st.plotly_chart(year_line_chart("bereik_per_post", "Bereik per post"),
                        use_container_width=True)

    # Volgers-groei grafiek
    def follower_chart():
        fig = go.Figure()
        sorted_years = sorted(selected_years)
        all_vals = []
        for year in sorted_years:
            color = YEAR_COLOR_MAP.get(year, YEAR_COLOR_DEFAULT)
            values = yearly_followers[year]
            all_vals.extend([v for v in values if v is not None])
            is_latest = (year == sorted_years[-1])
            fill_alpha = 0.15 if is_latest else 0.06
            fig.add_trace(go.Scatter(
                x=list(range(1, 13)), y=values,
                name=str(year),
                mode="lines+markers",
                line=dict(color=color, width=2.5, shape="spline"),
                marker=dict(color="white", size=7,
                            line=dict(color=color, width=2)),
                fill="tozeroy",
                fillcolor=_hex_to_rgba(color, fill_alpha),
                hovertemplate="%{text}: %{y:,.0f}<extra></extra>",
                text=[f"{MONTH_LABELS[m-1]} {year}" for m in range(1, 13)],
                connectgaps=True,
            ))
        follower_layout = dict(**layout_base)
        if all_vals:
            min_v = min(all_vals)
            max_v = max(all_vals)
            padding = (max_v - min_v) * 0.15 or max_v * 0.05
            follower_layout["yaxis"] = dict(**layout_base["yaxis"],
                                            range=[min_v - padding, max_v + padding])
        fig.update_layout(**follower_layout)
        return fig

    st.subheader("Volgers-groei")
    st.plotly_chart(follower_chart(), use_container_width=True)


def show_dashboard(page: str | None = None):
    """Overall dashboard with KPIs and monthly charts."""
    if page:
        label = page.capitalize()
        subtitle = f"{label} — Social Media Overzicht"
    else:
        label = "Totaal"
        subtitle = "Prins Petfoods & Edupet — Social Media Overzicht"
    st.header("Dashboard")
    st.caption(subtitle)

    stats = get_monthly_stats()
    all_posts = get_posts(page=page) if page else get_posts()

    if not all_posts:
        st.info("Nog geen data. Upload CSV's via de 'CSV Upload' tab.")
        return

    df_all = pd.DataFrame(all_posts)
    df_all["date_parsed"] = pd.to_datetime(df_all["date"], errors="coerce")

    # KPI cards — current month
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    df_month = df_all[df_all["date_parsed"].dt.strftime("%Y-%m") == current_month]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Posts deze maand", len(df_month))
    col2.metric("Totaal engagement", f"{df_month['engagement'].sum():,}")
    reach_val = df_month['reach'].mean() if len(df_month) > 0 else 0
    col3.metric("Gem. bereik", f"{reach_val:,.0f}" if pd.notna(reach_val) else "0")
    col4.metric("Totaal posts", len(df_all))

    # Monthly trend charts per jaar — per platform lijn
    if stats:
        df_stats = pd.DataFrame(stats)
        if page:
            df_stats = df_stats[df_stats["page"] == page]

        if not df_stats.empty:
            MONTH_LABELS = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
                            "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]
            YEAR_COLOR_MAP = {2024: "#0d5a4d", 2025: "#81b29a", 2026: "#d32f2f",
                              2027: "#3d405b", 2028: "#f2cc8f"}
            YEAR_COLOR_DEFAULT = "#86868b"

            df_stats["month_parsed"] = pd.to_datetime(df_stats["month"])
            df_stats["year"] = df_stats["month_parsed"].dt.year
            df_stats["month_num"] = df_stats["month_parsed"].dt.month

            available_years = sorted(df_stats["year"].unique().astype(int), reverse=True)

            selected_years = st.multiselect(
                "Jaren vergelijken",
                options=available_years,
                default=available_years,
                key="dashboard_allyears",
            )
            if not selected_years:
                return

            # Per platform: bouw lijnen per jaar
            platforms = sorted(df_stats["platform"].unique())
            PLATFORM_COLORS = {"facebook": "#0d5a4d", "instagram": "#81b29a",
                               "tiktok": "#3d405b"}

            def _hex_to_rgba(hex_color, alpha):
                h = hex_color.lstrip("#")
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                return f"rgba({r},{g},{b},{alpha})"

            layout_base = dict(
                font=dict(family="Inter, sans-serif", color="#1d1d1f"),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=20, r=20, t=10, b=40),
                xaxis=dict(
                    gridcolor="#f0f0f2", title=None,
                    tickvals=list(range(1, 13)), ticktext=MONTH_LABELS,
                    tickfont=dict(color="#86868b", size=11),
                    showline=False,
                ),
                yaxis=dict(
                    gridcolor="#f0f0f2", title=None,
                    tickfont=dict(color="#86868b", size=11),
                    showline=False, zeroline=False,
                ),
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1,
                            font=dict(size=12, color="#1d1d1f")),
                hoverlabel=dict(
                    bgcolor="white", bordercolor="#e0e0e0",
                    font=dict(family="Inter, sans-serif", size=13, color="#1d1d1f"),
                ),
                hovermode="x unified",
            )

            def overview_line_chart(metric, title):
                fig = go.Figure()
                sorted_yrs = sorted(selected_years)
                for year in sorted_yrs:
                    for plat in platforms:
                        df_yp = df_stats[(df_stats["year"] == year) & (df_stats["platform"] == plat)]
                        by_month = df_yp.groupby("month_num")[metric].sum()
                        by_month = by_month.reindex(range(1, 13))
                        yi = sorted_yrs.index(year)
                        base_color = PLATFORM_COLORS.get(plat, YEAR_COLOR_DEFAULT)
                        is_latest = (year == sorted_yrs[-1])
                        fill_alpha = 0.12 if is_latest else 0.04
                        line_width = 2.5 if is_latest else 1.5
                        fig.add_trace(go.Scatter(
                            x=list(range(1, 13)), y=by_month.values,
                            name=f"{plat.capitalize()} {year}",
                            mode="lines+markers",
                            line=dict(color=base_color, width=line_width,
                                      shape="spline",
                                      dash="solid" if is_latest else "dot"),
                            marker=dict(color="white", size=7 if is_latest else 5,
                                        line=dict(color=base_color, width=2)),
                            fill="tozeroy",
                            fillcolor=_hex_to_rgba(base_color, fill_alpha),
                            hovertemplate="%{text}: %{y:,.0f}<extra></extra>",
                            text=[f"{MONTH_LABELS[m-1]} {year}" for m in range(1, 13)],
                            connectgaps=True,
                        ))
                fig.update_layout(**layout_base)
                return fig

            st.subheader("Engagement per maand")
            st.plotly_chart(overview_line_chart("total_engagement", "Engagement per maand"),
                            use_container_width=True)
            st.subheader("Bereik per maand")
            st.plotly_chart(overview_line_chart("total_reach", "Bereik per maand"),
                            use_container_width=True)

            # Volgers-groei per platform
            def overview_follower_chart():
                fig = go.Figure()
                sorted_yrs = sorted(selected_years)
                all_vals = []
                for plat in platforms:
                    base_color = PLATFORM_COLORS.get(plat, YEAR_COLOR_DEFAULT)
                    values = []
                    for m in range(1, 13):
                        month_str = f"{sorted_yrs[-1]}-{m:02d}"
                        fc = get_follower_count(DEFAULT_DB, plat, page or "prins", month_str)
                        values.append(fc)
                    all_vals.extend([v for v in values if v is not None])
                    fig.add_trace(go.Scatter(
                        x=list(range(1, 13)), y=values,
                        name=plat.capitalize(),
                        mode="lines+markers",
                        line=dict(color=base_color, width=2.5, shape="spline"),
                        marker=dict(color="white", size=7,
                                    line=dict(color=base_color, width=2)),
                        fill="tozeroy",
                        fillcolor=_hex_to_rgba(base_color, 0.1),
                        hovertemplate="%{text}: %{y:,.0f}<extra></extra>",
                        text=[f"{MONTH_LABELS[m-1]}" for m in range(1, 13)],
                        connectgaps=True,
                    ))
                f_layout = dict(**layout_base)
                if all_vals:
                    min_v = min(all_vals)
                    max_v = max(all_vals)
                    padding = (max_v - min_v) * 0.15 or max_v * 0.05
                    f_layout["yaxis"] = dict(**layout_base["yaxis"],
                                             range=[min_v - padding, max_v + padding])
                fig.update_layout(**f_layout)
                return fig

            st.subheader(f"Volgers-groei {sorted(selected_years)[-1]}")
            st.plotly_chart(overview_follower_chart(), use_container_width=True)


def show_single_channel(platform: str, page: str):
    """Show dashboard + posts for a single platform/page combination."""
    if platform == "tiktok":
        # TikTok sync
        sync_tiktok_followers(page)
        sync_tiktok_videos(page)
    else:
        # Meta sync (Facebook/Instagram)
        sync_posts_from_api(page)
        sync_follower_current(page)

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

    show_channel_dashboard(platform, page)

    st.subheader("Posts")
    show_posts_table(platform, page)


@st.cache_data(ttl=3600)
def _ai_analyze_posts(_post_ids: tuple, platform: str, page: str,
                      follower_count: int | None) -> str:
    posts = get_posts(platform=platform, page=page)
    return ai_insights.analyze_posts(posts, platform, page, follower_count)


@st.cache_data(ttl=3600)
def _ai_monthly_report(_post_ids: tuple, platform: str, page: str,
                       month: str, follower_count: int | None) -> str:
    posts = get_posts(platform=platform, page=page)
    return ai_insights.generate_monthly_report(posts, platform, page, month, follower_count)


@st.cache_data(ttl=3600)
def _ai_suggest_content(_post_ids: tuple, platform: str, page: str,
                        follower_count: int | None) -> str:
    posts = get_posts(platform=platform, page=page)
    return ai_insights.suggest_content(posts, platform, page, follower_count)


@st.cache_data(ttl=300)
def _gather_all_data() -> tuple[dict[str, list[dict]], dict[str, int | None]]:
    """Verzamel alle post-data en volgers voor alle merken/platformen (cached 5 min)."""
    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    channels = [
        ("prins", "instagram"), ("prins", "facebook"), ("prins", "tiktok"),
        ("edupet", "instagram"), ("edupet", "facebook"),
    ]
    all_posts = {}
    follower_counts = {}
    for page, platform in channels:
        key = f"{page}_{platform}"
        posts = get_posts(platform=platform, page=page)
        if posts:
            all_posts[key] = posts
        follower_counts[key] = get_follower_count(DEFAULT_DB, platform, page, current_month)
    return all_posts, follower_counts


@st.cache_data(ttl=3600)
def _ai_cross_analyze(_post_hash: str) -> str:
    all_posts, follower_counts = _gather_all_data()
    return ai_insights.analyze_cross_platform(all_posts, follower_counts)


@st.cache_data(ttl=3600)
def _ai_cross_report(_post_hash: str, month: str) -> str:
    all_posts, follower_counts = _gather_all_data()
    return ai_insights.generate_cross_platform_report(all_posts, follower_counts, month)


@st.cache_data(ttl=3600)
def _ai_cross_suggest(_post_hash: str) -> str:
    all_posts, follower_counts = _gather_all_data()
    return ai_insights.suggest_content_cross_platform(all_posts, follower_counts)


def _show_ai_page():
    """AI Inzichten als eigen pagina — cross-platform analyse."""
    st.header(":material/auto_awesome: AI Inzichten")
    st.caption("Analyse over alle kanalen — Prins & Edupet")

    now = datetime.now(timezone.utc)
    current_month = now.strftime("%Y-%m")
    all_posts, follower_counts = _gather_all_data()
    total_count = sum(len(p) for p in all_posts.values())
    post_hash = f"{total_count}_{current_month}"

    tab_chat, tab_rapport, tab_analyse, tab_suggesties = st.tabs(
        ["Chat", "Maandrapport", "Analyse", "Content suggesties"]
    )

    with tab_chat:
        chat_key = "ai_cross_chat"
        summary_key = "ai_cross_summary"
        if chat_key not in st.session_state:
            st.session_state[chat_key] = []

        # Cache de data-samenvatting in session_state (bouw 1x, hergebruik)
        if summary_key not in st.session_state or not st.session_state[summary_key]:
            st.session_state[summary_key] = ai_insights.build_cross_platform_summary(
                all_posts, follower_counts)

        for msg in st.session_state[chat_key]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Stel een vraag over alle social media data...",
                                   key="ai_page_chat_input"):
            st.session_state[chat_key].append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                answer = st.write_stream(
                    ai_insights.chat_with_data_stream(
                        st.session_state[summary_key],
                        st.session_state[chat_key]))
            st.session_state[chat_key].append(
                {"role": "assistant", "content": answer})

    with tab_rapport:
        maand_opties = []
        all_months = set()
        for posts in all_posts.values():
            for p in posts:
                m = (p.get("date") or "")[:7]
                if m:
                    all_months.add(m)
        for m in sorted(all_months, reverse=True)[:12]:
            mm = m[5:7]
            label = f"{MAAND_NL.get(int(mm), mm)} {m[:4]}"
            maand_opties.append((label, m))

        if maand_opties:
            selected_label = st.selectbox(
                "Maand", [m[0] for m in maand_opties], key="ai_page_month")
            selected_month = next(m[1] for m in maand_opties
                                  if m[0] == selected_label)
        else:
            selected_month = current_month

        # Check for existing saved report
        saved = get_report(DEFAULT_DB, selected_month, platform="cross", page="")

        if saved:
            st.markdown(saved)
            if st.button(":material/refresh: Opnieuw genereren", key="ai_page_rapport_regen"):
                with st.spinner("AI schrijft rapport..."):
                    result = _ai_cross_report(post_hash, selected_month)
                    save_report(DEFAULT_DB, selected_month, result, platform="cross", page="")
                    st.rerun()
        else:
            if st.button(":material/description: Genereer rapport", key="ai_page_rapport_btn"):
                with st.spinner("AI schrijft rapport..."):
                    result = _ai_cross_report(post_hash, selected_month)
                    save_report(DEFAULT_DB, selected_month, result, platform="cross", page="")
                    st.rerun()

    with tab_analyse:
        if st.button("Genereer analyse", key="ai_page_analyse_btn"):
            with st.spinner("AI analyseert..."):
                result = _ai_cross_analyze(post_hash)
                st.session_state["ai_page_analyse"] = result
        if "ai_page_analyse" in st.session_state:
            st.markdown(st.session_state["ai_page_analyse"])

    with tab_suggesties:
        if st.button("Genereer suggesties", key="ai_page_suggesties_btn"):
            with st.spinner("AI bedenkt content..."):
                result = _ai_cross_suggest(post_hash)
                st.session_state["ai_page_suggesties"] = result
        if "ai_page_suggesties" in st.session_state:
            st.markdown(st.session_state["ai_page_suggesties"])


def _show_remarks_page():
    """Opmerkingenbord als eigen pagina."""
    st.header(":material/comment: Opmerkingen")
    st.caption("Feedback en wijzigingsverzoeken")

    # Nieuwe opmerking plaatsen
    st.subheader("Nieuwe opmerking")
    with st.form("remark_form", clear_on_submit=True):
        remark_author = st.text_input("Naam", placeholder="Jouw naam")
        remark_msg = st.text_area("Opmerking", placeholder="Wat moet er veranderd worden?",
                                  height=120)
        remark_submit = st.form_submit_button("Plaatsen", use_container_width=True)
    if remark_submit and remark_author and remark_msg:
        add_remark(DEFAULT_DB, remark_author, remark_msg)
        st.success("Opmerking geplaatst!")
        st.rerun()

    # Bestaande opmerkingen
    remarks = get_remarks()
    open_remarks = [r for r in remarks if r.get("status") != "afgehandeld"]
    done_remarks = [r for r in remarks if r.get("status") == "afgehandeld"]

    st.subheader(f"Open ({len(open_remarks)})")
    if open_remarks:
        for r in open_remarks:
            ts = (r.get("created_at") or "")[:16].replace("T", " ")
            col_msg, col_btn = st.columns([5, 1])
            with col_msg:
                st.markdown(f"**{r.get('author', '')}** *{ts}*")
                st.markdown(r.get("message", ""))
            with col_btn:
                if st.button("Afhandelen", key=f"remark_done_{r['id']}"):
                    update_remark_status(DEFAULT_DB, r["id"], "afgehandeld")
                    st.rerun()
    else:
        st.caption("Geen openstaande opmerkingen.")

    if done_remarks:
        with st.expander(f"Afgehandeld ({len(done_remarks)})", expanded=False):
            for r in done_remarks:
                ts = (r.get("created_at") or "")[:16].replace("T", " ")
                st.markdown(f"~~{r.get('message', '')}~~ — **{r.get('author', '')}** *{ts}*")


def main():
    # ── Sidebar navigatie ──
    if "nav" not in st.session_state:
        st.session_state.nav = "prins_instagram"

    def set_nav(value):
        st.session_state.nav = value

    try:
        st.logo("files/prins_logo.png")
    except Exception:
        pass

    with st.sidebar:
        st.caption("SOCIAL TRACKER")

        _active_nav = st.session_state.nav

        with st.expander(":material/pets: Prins", expanded=st.session_state.nav.startswith("prins")):
            st.button(":material/photo_camera: Instagram", key="btn_prins_ig",
                      use_container_width=True,
                      on_click=set_nav, args=("prins_instagram",),
                      type="primary" if _active_nav == "prins_instagram" else "secondary")
            st.button(":material/public: Facebook", key="btn_prins_fb",
                      use_container_width=True,
                      on_click=set_nav, args=("prins_facebook",),
                      type="primary" if _active_nav == "prins_facebook" else "secondary")
            st.button(":material/music_note: TikTok", key="btn_prins_tk",
                      use_container_width=True,
                      on_click=set_nav, args=("prins_tiktok",),
                      type="primary" if _active_nav == "prins_tiktok" else "secondary")

        with st.expander(":material/pets: Edupet", expanded=st.session_state.nav.startswith("edupet")):
            st.button(":material/photo_camera: Instagram", key="btn_edupet_ig",
                      use_container_width=True,
                      on_click=set_nav, args=("edupet_instagram",),
                      type="primary" if _active_nav == "edupet_instagram" else "secondary")
            st.button(":material/public: Facebook", key="btn_edupet_fb",
                      use_container_width=True,
                      on_click=set_nav, args=("edupet_facebook",),
                      type="primary" if _active_nav == "edupet_facebook" else "secondary")

        st.button(":material/auto_awesome: AI Inzichten", key="btn_ai",
                  use_container_width=True,
                  on_click=set_nav, args=("ai_insights",),
                  type="primary" if _active_nav == "ai_insights" else "secondary")

        st.button(":material/comment: Opmerkingen", key="btn_remarks",
                  use_container_width=True,
                  on_click=set_nav, args=("remarks",),
                  type="primary" if _active_nav == "remarks" else "secondary")

        # ── Token status ──
        if _tokens_valid:
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



    # ── Content ──
    _page_fade_in()
    nav = st.session_state.nav
    if nav == "ai_insights":
        _show_ai_page()
    elif nav == "remarks":
        _show_remarks_page()
    elif nav == "prins_instagram":
        show_single_channel("instagram", "prins")
    elif nav == "prins_facebook":
        show_single_channel("facebook", "prins")
    elif nav == "prins_tiktok":
        show_single_channel("tiktok", "prins")
    elif nav == "edupet_instagram":
        show_single_channel("instagram", "edupet")
    elif nav == "edupet_facebook":
        show_single_channel("facebook", "edupet")


def show_terms_of_service():
    """Gebruiksvoorwaarden pagina."""
    st.title("Gebruiksvoorwaarden")
    st.caption("Prins Social Tracker")
    st.markdown("""
**Laatst bijgewerkt: februari 2026**

### 1. Dienst
Prins Social Tracker ("de App") is een intern social media dashboard
ontwikkeld door en voor Prins Petfoods B.V. De App verzamelt en toont
statistieken van sociale-mediakanalen die aan Prins Petfoods zijn gekoppeld.

### 2. Toegang
De App is uitsluitend bedoeld voor geautoriseerde medewerkers en partners
van Prins Petfoods B.V. Toegang wordt verleend op uitnodiging.

### 3. Gebruik van gegevens
De App maakt verbinding met sociale-mediaplatforms (Meta, TikTok) via
hun officiële API's. Alleen publieke statistieken en eigen accountgegevens
worden opgehaald. Er worden geen persoonsgegevens van derden verzameld.

### 4. Intellectueel eigendom
Alle rechten op de App, inclusief het ontwerp en de broncode, berusten bij
Prins Petfoods B.V.

### 5. Aansprakelijkheid
De App wordt aangeboden "as is". Prins Petfoods B.V. is niet aansprakelijk
voor onbeschikbaarheid, gegevensverlies of onjuiste statistieken die
voortvloeien uit wijzigingen in externe API's.

### 6. Contact
Prins Petfoods B.V.
Huizermaatweg 280
1276 LJ Huizen
Nederland
info@prins.nl
""")


def show_privacy_policy():
    """Privacybeleid pagina."""
    st.title("Privacybeleid")
    st.caption("Prins Social Tracker")
    st.markdown("""
**Laatst bijgewerkt: februari 2026**

### 1. Verwerkingsverantwoordelijke
Prins Petfoods B.V.
Huizermaatweg 280
1276 LJ Huizen
Nederland
info@prins.nl

### 2. Welke gegevens verwerken wij?
De App verwerkt uitsluitend:
- **Accountstatistieken** van eigen social-mediakanalen (volgers, views,
  likes, reacties, shares) via de officiële API's van Meta en TikTok.
- **Inloggegevens** van geautoriseerde gebruikers (e-mailadres of
  gebruikersnaam) voor toegangsbeheer.

Wij verzamelen **geen** persoonsgegevens van volgers of bezoekers van
de sociale-mediakanalen.

### 3. Doel van verwerking
De gegevens worden uitsluitend gebruikt voor interne rapportage en
analyse van social media prestaties van Prins Petfoods.

### 4. Bewaartermijn
Statistieken worden bewaard zolang nodig voor rapportagedoeleinden.
Toegangsgegevens worden verwijderd wanneer een gebruiker geen toegang
meer nodig heeft.

### 5. Delen met derden
Gegevens worden niet gedeeld met derden, behalve met de API-providers
(Meta, TikTok) voor het ophalen van statistieken conform hun
ontwikkelaarsvoorwaarden.

### 6. Beveiliging
Toegang is beperkt tot geautoriseerde gebruikers. API-tokens worden
versleuteld opgeslagen. De App maakt gebruik van beveiligde
HTTPS-verbindingen.

### 7. Uw rechten
U heeft het recht op inzage, correctie en verwijdering van uw gegevens.
Neem hiervoor contact op via info@prins.nl.

### 8. Cookies
De App maakt gebruik van functionele sessiecookies die noodzakelijk
zijn voor de werking. Er worden geen tracking- of advertentiecookies
gebruikt.
""")


# ── Entrypoint: check query parameters voor legal pages ──
_query_params = st.query_params
_page_param = _query_params.get("page", "")

if _page_param == "terms":
    show_terms_of_service()
elif _page_param == "privacy":
    show_privacy_policy()
elif __name__ == "__main__":
    main()
