# app.py
"""Prins Social Tracker — Streamlit Dashboard."""

import os
import tempfile
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from dotenv import load_dotenv

from csv_import import detect_platform, parse_csv_file
from database import (
    DEFAULT_DB,
    get_follower_previous_month,
    get_monthly_stats,
    get_posts,
    get_uploads,
    init_db,
    insert_posts,
    log_upload,
    save_follower_snapshot,
    update_post_labels,
)

load_dotenv()


def _get_secret(key: str, default: str = "") -> str:
    """Haal waarde op uit st.secrets (Streamlit Cloud) of os.getenv (lokaal)."""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.getenv(key, default)


st.set_page_config(
    page_title="Prins Social Tracker",
    page_icon="📊",
    layout="wide",
)

# Init database on startup
init_db()

# ── Custom styling ──
st.markdown("""
<style>
</style>
""", unsafe_allow_html=True)

# ── Meta Graph API ──
FB_API_VERSION = "v22.0"
FB_BASE_URL = f"https://graph.facebook.com/{FB_API_VERSION}"
META_APP_ID = _get_secret("META_APP_ID")
META_APP_SECRET = _get_secret("META_APP_SECRET")

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def _check_token(token: str) -> bool:
    """Check of een token nog geldig is."""
    if not token:
        return False
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/debug_token",
            params={"input_token": token, "access_token": token},
            timeout=10, verify=False,
        )
        data = resp.json().get("data", {})
        return data.get("is_valid", False)
    except Exception:
        return False


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
            timeout=10, verify=False,
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
            timeout=10, verify=False,
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
            timeout=15, verify=False,
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
            timeout=15, verify=False,
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
                timeout=15, verify=False,
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
            timeout=15, verify=False,
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
            timeout=10, verify=False,
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
                timeout=10, verify=False,
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
                            timeout=10, verify=False,
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


# ── Prins Petfoods design system (Apple-inspired) ──
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* ── Global ── */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'SF Pro Display',
                     'Helvetica Neue', Arial, sans-serif;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    .main .block-container { padding-top: 2rem; }

    /* ── Header bar ── */
    header[data-testid="stHeader"] {
        background-color: #fff;
    }

    /* ── Typography ── */
    h1, h2, h3 {
        color: #1d1d1f !important;
        font-weight: 600;
        letter-spacing: -0.02em;
    }
    h2 { font-size: 2rem; }
    h3 { font-size: 1.4rem; }

    /* ── Metric cards ── */
    [data-testid="stMetric"] {
        background: #0d5a4d;
        border: none;
        border-radius: 18px;
        padding: 20px 24px;
        box-shadow: none;
    }
    [data-testid="stMetric"] label,
    [data-testid="stMetricLabel"] {
        color: rgba(255,255,255,0.7) !important;
        font-size: 0.75rem !important;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.01em;
    }
    [data-testid="stMetricValue"] {
        font-weight: 600;
        color: #fff;
        font-size: 1.3rem;
    }
    [data-testid="stMetricDelta"],
    [data-testid="stMetricDelta"] > div {
        font-size: 0.85rem;
        color: #fff !important;
        font-weight: 600;
        background: transparent !important;
        background-color: transparent !important;
    }
    [data-testid="stMetricDelta"] svg {
        display: none !important;
    }

    /* ── Buttons (main content) ── */
    .main .stButton > button {
        background-color: #0d5a4d !important;
        color: white !important;
        border: none !important;
        border-radius: 980px !important;
        padding: 10px 24px !important;
        font-size: 0.9rem !important;
        font-weight: 500 !important;
        transition: background-color 0.2s ease !important;
    }
    .main .stButton > button:hover {
        background-color: #0a4a3f !important;
        color: white !important;
    }

    /* ── Sidebar nav buttons ── */
    section[data-testid="stSidebar"] .stButton > button {
        background: transparent !important;
        color: #1d1d1f !important;
        border: none !important;
        border-radius: 8px !important;
        padding: 6px 12px !important;
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        text-align: left !important;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        background: rgba(162, 196, 186, 0.2) !important;
    }
    section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
        background: rgba(162, 196, 186, 0.3) !important;
        border-left: 3px solid #0d5a4d !important;
        border-radius: 0 8px 8px 0 !important;
        font-weight: 600 !important;
    }

    /* ── Inputs & selects ── */
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input {
        border: 1px solid #d2d2d7 !important;
        border-radius: 12px !important;
        padding: 10px 14px !important;
        font-size: 0.95rem !important;
        background: #fff !important;
        transition: border-color 0.2s ease !important;
    }
    .stTextInput > div > div > input:focus,
    .stNumberInput > div > div > input:focus {
        border-color: #0d5a4d !important;
        box-shadow: 0 0 0 3px rgba(13,90,77,0.15) !important;
    }
    [data-baseweb="select"] {
        border-radius: 12px !important;
    }
    .stMultiSelect [data-baseweb="tag"] {
        background-color: #0d5a4d !important;
        border-radius: 8px !important;
    }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 1px solid #f0f0f2;
    }
    .stTabs [data-baseweb="tab"] {
        color: #86868b;
        font-weight: 500;
        padding: 0.75rem 1.25rem;
        border-radius: 0;
    }
    .stTabs [aria-selected="true"] {
        color: #1d1d1f;
        font-weight: 600;
        border-bottom: 2px solid #0d5a4d;
        background: transparent;
    }

    /* ── Expanders ── */
    [data-testid="stExpander"] {
        border: 1px solid #d2d2d7;
        border-radius: 18px;
        box-shadow: none;
        overflow: hidden;
    }

    /* ── Data tables ── */
    [data-testid="stDataFrame"] {
        border: 1px solid #f0f0f2;
        border-radius: 18px;
    }

    /* ── Success messages ── */
    .stSuccess {
        background-color: rgba(13,90,77,0.06);
        border-left-color: #0d5a4d;
    }

    /* ── Dividers ── */
    hr {
        border-color: #f0f0f2 !important;
    }

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {
        background: #fff;
        border-right: none;
    }
    section[data-testid="stSidebar"] * {
        color: #1d1d1f;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] {
        background-color: transparent;
        border: none !important;
        box-shadow: none !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] details {
        background-color: transparent;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
        background-color: #0d5a4d;
        border-radius: 14px;
        color: #fff !important;
        font-weight: 600;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
        background-color: #0a4a3f;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] summary * {
        color: #fff !important;
    }
    section[data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        background-color: transparent;
        border: none;
    }
    section[data-testid="stSidebar"] .stButton > button {
        background-color: transparent !important;
        color: #1d1d1f !important;
        border: none !important;
        border-radius: 10px !important;
        text-align: left;
        font-weight: 500;
        padding: 8px 16px !important;
    }
    section[data-testid="stSidebar"] .stButton > button:hover {
        background-color: rgba(13,90,77,0.06) !important;
        color: #0d5a4d !important;
    }

    /* ── Caption text ── */
    .stCaption, [data-testid="stCaptionContainer"] {
        color: #86868b;
    }

    /* ── Page transition spinner ── */
    @keyframes pf-spin { to { transform: rotate(360deg); } }
    body:has([data-testid="stSidebar"] [data-stale="true"]) [data-testid="stMain"]::before {
        content: ""; position: fixed; inset: 0; background: #fff; z-index: 9998;
    }
    body:has([data-testid="stSidebar"] [data-stale="true"]) [data-testid="stMain"]::after {
        content: ""; position: fixed; top: 50%; left: 50%;
        width: 28px; height: 28px; margin: -14px 0 0 -14px;
        border: 3px solid #e5e5ea; border-top-color: #0d5a4d;
        border-radius: 50%; animation: pf-spin 0.6s linear infinite; z-index: 9999;
    }

    /* ── Login page ── */
    .login-container {
        max-width: 400px;
        margin: 4rem auto;
        padding: 2rem;
        background: #fff;
        border-radius: 18px;
        border: 1px solid #d2d2d7;
    }
</style>
""", unsafe_allow_html=True)

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
        st.markdown("""
        <div style="text-align: center; padding: 2rem 0 1rem;">
            <h1 style="color: #1d1d1f; margin-bottom: 0.25rem; letter-spacing: -0.02em;">Prins Social Tracker</h1>
            <p style="color: #86868b; font-size: 1.1rem;">Social media dashboard</p>
        </div>
        """, unsafe_allow_html=True)
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
    df["year"] = df["date_parsed"].dt.year
    df["month_num"] = df["date_parsed"].dt.month
    df = df.sort_values("date_parsed", ascending=False)

    display_cols = ["datum_fmt", "type", "text", "reach", "impressions", "likes",
                    "comments", "shares", "clicks", "engagement",
                    "engagement_rate", "theme", "campaign"]
    col_labels = {
        "datum_fmt": "Datum", "type": "Type", "text": "Omschrijving",
        "reach": "Bereik", "impressions": "Weergaven", "likes": "Likes",
        "comments": "Reacties", "shares": "Shares", "clicks": "Klikken",
        "engagement": "Engagement", "engagement_rate": "ER%",
        "theme": "Thema", "campaign": "Campagne",
    }

    years = sorted(df["year"].dropna().unique(), reverse=True)
    for year in years:
        year_df = df[df["year"] == year]
        year_int = int(year)
        with st.expander(f"{year_int}", expanded=(year == years[0])):
            months = sorted(year_df["month_num"].dropna().unique())
            for month in months:
                month_df = year_df[year_df["month_num"] == month]
                month_name = MAAND_NL.get(int(month), str(int(month)))
                st.markdown(f"**{month_name}**")

                display_df = month_df[["id"] + display_cols].copy()
                display_df = display_df.rename(columns=col_labels)

                editor_key = f"{key_prefix}_{year_int}_{int(month)}_editor"
                edited = st.data_editor(
                    display_df,
                    disabled=[c for c in display_df.columns
                              if c not in ("Thema", "Campagne")],
                    hide_index=True,
                    use_container_width=True,
                    key=editor_key,
                )

                # Save changes
                if not edited.equals(display_df):
                    save_key = f"{key_prefix}_{year_int}_{int(month)}_save"
                    if st.button("Wijzigingen opslaan", key=save_key):
                        for idx in range(len(edited)):
                            row = edited.iloc[idx]
                            orig_row = display_df.iloc[idx] if idx < len(display_df) else None
                            if orig_row is not None:
                                if row["Thema"] != orig_row["Thema"] or row["Campagne"] != orig_row["Campagne"]:
                                    theme_val = row["Thema"] if pd.notna(row["Thema"]) else ""
                                    campaign_val = row["Campagne"] if pd.notna(row["Campagne"]) else ""
                                    update_post_labels(DEFAULT_DB, int(row["id"]), theme_val, campaign_val)
                        st.success("Labels opgeslagen!")

                st.caption(f"{len(month_df)} posts | Engagement: {month_df['engagement'].sum():,} | "
                           f"Gem. bereik: {month_df['reach'].mean():,.0f}")


def show_brand_page(page: str):
    """Show Facebook + Instagram with separate dashboards per channel."""
    label = page.capitalize()
    st.markdown(f"""
    <div style="padding: 0.5rem 0 1rem;">
        <h2 style="color: #1d1d1f; margin-bottom: 0.25rem; letter-spacing: -0.02em;">{label}</h2>
        <p style="color: #86868b;">Facebook &amp; Instagram overzicht</p>
    </div>
    """, unsafe_allow_html=True)

    tab_fb, tab_ig = st.tabs(["Facebook", "Instagram"])

    with tab_fb:
        st.subheader(f"{label} — Facebook")
        show_channel_dashboard("facebook", page)
        st.markdown("<hr style='border-color: #a2c4ba; margin: 1.5rem 0;'>",
                    unsafe_allow_html=True)
        st.subheader("Posts")
        show_posts_table("facebook", page)

    with tab_ig:
        st.subheader(f"{label} — Instagram")
        show_channel_dashboard("instagram", page)
        st.markdown("<hr style='border-color: #a2c4ba; margin: 1.5rem 0;'>",
                    unsafe_allow_html=True)
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
    from database import _connect
    _conn = _connect(DEFAULT_DB)
    _row = _conn.execute(
        "SELECT followers FROM follower_snapshots WHERE platform = ? AND page = ? AND month = ?",
        (platform, page, current_month),
    ).fetchone()
    _conn.close()
    follower_count = _row["followers"] if _row else None

    follower_delta = None
    if follower_count is not None:
        prev = get_follower_previous_month(DEFAULT_DB, platform, page)
        if prev is not None:
            follower_delta = follower_count - prev

    col1, col2, col3, col4, col5 = st.columns(5)
    if follower_count is not None:
        if follower_delta is not None:
            arrow = "↑" if follower_delta >= 0 else "↓"
            col1.metric("Volgers", f"{follower_count:,}",
                         delta=f"{arrow} {follower_delta:+,} deze maand")
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
        arrow = "↑" if diff >= 0 else "↓"
        posts_delta_str = f"{arrow} {diff:+.0f} vs. gem."
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
            arrow = "↑" if diff >= 0 else "↓"
            impressions_delta_str = f"{arrow} {diff:+,.0f} vs. gem."
    col3.metric("Gem. weergaven/post (deze maand)",
                f"{impressions_per_post:,.0f}" if pd.notna(impressions_per_post) else "0",
                delta=impressions_delta_str)
    reach_per_post = df_month['reach'].mean() if len(df_month) > 0 else 0
    reach_delta_str = None
    if len(df_prev_months) > 0:
        prev_reach_per_post = df_prev_months.groupby(
            df_prev_months["date_parsed"].dt.strftime("%Y-%m")
        )['reach'].mean()
        if len(prev_reach_per_post) > 0:
            avg_reach = prev_reach_per_post.mean()
            diff = reach_per_post - avg_reach
            arrow = "↑" if diff >= 0 else "↓"
            reach_delta_str = f"{arrow} {diff:+,.0f} vs. gem."
    col4.metric("Gem. bereik/post (deze maand)",
                f"{reach_per_post:,.0f}" if pd.notna(reach_per_post) else "0",
                delta=reach_delta_str)

    # Engagement Rate deze maand vs. langlopend gemiddelde
    er_current = None
    er_avg = None
    if len(df_month) > 0 and follower_count and follower_count > 0:
        er_current = (df_month['engagement'].sum() / len(df_month)) / follower_count * 100

        # Langlopend gemiddelde: alle voorgaande maanden (excl. huidige)
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
            arrow = "↑" if diff >= 0 else "↓"
            er_delta_str = f"{arrow} {diff:+.2f}% vs. gem."
        col5.metric("Engagement Rate (deze maand)", f"{er_current:.2f}%", delta=er_delta_str)
    else:
        col5.metric("Engagement Rate (deze maand)", "–")

    # Monthly trend line charts per jaar
    df_all["year"] = df_all["date_parsed"].dt.year
    df_all["month_num"] = df_all["date_parsed"].dt.month

    available_years = sorted(df_all["year"].dropna().unique().astype(int), reverse=True)
    if not available_years:
        return

    key_prefix = f"{page}_{platform}"
    MONTH_LABELS = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
                    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]
    YEAR_COLORS = ["#0d5a4d", "#81b29a", "#d32f2f", "#3d405b", "#f2cc8f"]

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
            likes=("likes", "sum"),
            reacties=("comments", "sum"),
            er=("engagement_rate", "mean"),
        )
        by_month = by_month.reindex(range(1, 13))
        yearly_data[year] = by_month

    layout_base = dict(
        font=dict(
            family="-apple-system, BlinkMacSystemFont, 'Inter', sans-serif",
            color="#1d1d1f",
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=50, b=40),
        xaxis=dict(
            gridcolor="#f0f0f2", title=None,
            tickvals=list(range(1, 13)), ticktext=MONTH_LABELS,
            tickfont=dict(color="#86868b", size=11),
        ),
        yaxis=dict(
            gridcolor="#f0f0f2", title=None,
            tickfont=dict(color="#86868b", size=11),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1,
                    font=dict(size=12, color="#1d1d1f")),
    )

    def year_line_chart(metric, title):
        fig = go.Figure()
        hover_fmt = "%{text}: %{y:.2f}%%<extra></extra>" if metric == "er" else "%{text}: %{y:,.0f}<extra></extra>"
        for i, year in enumerate(sorted(selected_years)):
            color = YEAR_COLORS[i % len(YEAR_COLORS)]
            values = yearly_data[year][metric]
            fig.add_trace(go.Scatter(
                x=list(range(1, 13)), y=values,
                name=str(year),
                mode="lines+markers",
                line=dict(color=color, width=2),
                marker=dict(color=color, size=6),
                hovertemplate=hover_fmt,
                text=[f"{MONTH_LABELS[m-1]} {year}" for m in range(1, 13)],
            ))
        fig.update_layout(
            title=dict(text=title, font=dict(size=13, color="#1d1d1f")),
            **layout_base,
        )
        return fig

    st.plotly_chart(year_line_chart("bereik", "Organisch bereik"),
                    use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(year_line_chart("er", "E.R. per post (gem. per maand)"),
                        use_container_width=True)
    with col_b:
        st.plotly_chart(year_line_chart("likes", "Likes per maand"),
                        use_container_width=True)

    st.plotly_chart(year_line_chart("posts", "Aantal posts per maand"),
                    use_container_width=True)


def show_dashboard(page: str | None = None):
    """Overall dashboard with KPIs and monthly charts."""
    if page:
        label = page.capitalize()
        subtitle = f"{label} — Social Media Overzicht"
    else:
        label = "Totaal"
        subtitle = "Prins Petfoods &amp; Edupet — Social Media Overzicht"
    st.markdown(f"""
    <div style="padding: 0.5rem 0 1rem;">
        <h2 style="color: #1d1d1f; margin-bottom: 0.25rem; letter-spacing: -0.02em;">Dashboard</h2>
        <p style="color: #86868b;">{subtitle}</p>
    </div>
    """, unsafe_allow_html=True)

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
            YEAR_COLORS = ["#0d5a4d", "#81b29a", "#d32f2f", "#3d405b", "#f2cc8f"]

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
            PLATFORM_COLORS = {"facebook": "#0d5a4d", "instagram": "#a2c4ba"}

            layout_base = dict(
                font=dict(family="Inter, sans-serif", color="#0d5a4d"),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=20, r=20, t=40, b=40),
                xaxis=dict(
                    gridcolor="#e0ece9", title=None,
                    tickvals=list(range(1, 13)), ticktext=MONTH_LABELS,
                ),
                yaxis=dict(gridcolor="#e0ece9", title=None),
                legend=dict(orientation="h", yanchor="bottom", y=1.02,
                            xanchor="right", x=1, font=dict(size=12)),
            )

            def overview_line_chart(metric, title):
                fig = go.Figure()
                for year in sorted(selected_years):
                    for plat in platforms:
                        df_yp = df_stats[(df_stats["year"] == year) & (df_stats["platform"] == plat)]
                        by_month = df_yp.groupby("month_num")[metric].sum()
                        by_month = by_month.reindex(range(1, 13))
                        yi = sorted(selected_years).index(year)
                        base_color = PLATFORM_COLORS.get(plat, YEAR_COLORS[0])
                        # Vary opacity for older years
                        opacity = 1.0 if yi == len(selected_years) - 1 else 0.5
                        dash = "solid" if yi == len(selected_years) - 1 else "dot"
                        fig.add_trace(go.Scatter(
                            x=list(range(1, 13)), y=by_month.values,
                            name=f"{plat.capitalize()} {year}",
                            mode="lines+markers",
                            line=dict(color=base_color, width=2.5, dash=dash),
                            marker=dict(color=base_color, size=7),
                            opacity=opacity,
                            hovertemplate="%{text}: %{y:,.0f}<extra></extra>",
                            text=[f"{MONTH_LABELS[m-1]} {year}" for m in range(1, 13)],
                        ))
                fig.update_layout(
                    title=dict(text=title, font=dict(size=16, color="#0d5a4d")),
                    **layout_base,
                )
                return fig

            st.plotly_chart(overview_line_chart("total_engagement", "Engagement per maand"),
                            use_container_width=True)
            st.plotly_chart(overview_line_chart("total_posts", "Aantal posts per maand"),
                            use_container_width=True)
            st.plotly_chart(overview_line_chart("total_reach", "Bereik per maand"),
                            use_container_width=True)


def show_single_channel(platform: str, page: str):
    """Show dashboard + posts for a single platform/page combination."""
    # Auto-sync posts via API (gecached voor 15 min)
    sync_posts_from_api(page)
    # Sync huidige volgers (gecached voor 15 min)
    sync_follower_current(page)

    label = page.capitalize()
    plat_label = platform.capitalize()

    if platform == "facebook":
        _plat_icon = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="#0d5a4d" stroke="none"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg>'
    else:
        _plat_icon = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0d5a4d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><circle cx="12" cy="12" r="5"/><circle cx="17.5" cy="6.5" r="1.5" fill="#0d5a4d" stroke="none"/></svg>'

    st.markdown(f"""
    <div style="padding: 0.5rem 0 0.75rem;">
        <h2 style="color: #1d1d1f; margin: 0; letter-spacing: -0.02em; font-size: 1.6rem;
                   display: flex; align-items: center; gap: 0.5rem;">
            {plat_label} <span style="display: inline-flex;">{_plat_icon}</span>
        </h2>
        <p style="color: #86868b; margin: 0.2rem 0 0; font-size: 1.05rem;">{label} overzicht</p>
        <div style="width: 40px; height: 3px; background: #0d5a4d; border-radius: 2px; margin-top: 0.6rem;"></div>
    </div>
    """, unsafe_allow_html=True)

    show_channel_dashboard(platform, page)
    st.markdown("<hr style='border-color: #a2c4ba; margin: 1.5rem 0;'>",
                unsafe_allow_html=True)
    st.subheader("Posts")
    show_posts_table(platform, page)


def main():
    # ── Sidebar navigatie ──
    if "nav" not in st.session_state:
        st.session_state.nav = "prins_instagram"

    def set_nav(value):
        st.session_state.nav = value

    with st.sidebar:
        import base64, pathlib
        _logo_bytes = pathlib.Path("files/prins_logo.png").read_bytes()
        _logo_b64 = base64.b64encode(_logo_bytes).decode()
        st.markdown(f"""
        <div style="text-align: center; padding: 0 1rem 0.4rem; margin-top: -1rem;">
            <img src="data:image/png;base64,{_logo_b64}" style="width: 120px;">
            <p style="color: #a2c4ba; font-size: 0.7rem; letter-spacing: 0.15em;
                      text-transform: uppercase; margin: 0.4rem 0 0; font-weight: 500;">
                Social Tracker</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<hr style='border-color: #1a7a6a; margin: 0.5rem 0 3rem;'>",
                    unsafe_allow_html=True)

        _PRINS_GREEN = "#0d5a4d"
        _IG_ICON = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{_PRINS_GREEN}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><circle cx="12" cy="12" r="5"/><circle cx="17.5" cy="6.5" r="1.5" fill="{_PRINS_GREEN}" stroke="none"/></svg>'''
        _FB_ICON = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="{_PRINS_GREEN}" stroke="none"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg>'''
        _CSV_ICON = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="{_PRINS_GREEN}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="8" y1="13" x2="16" y2="13"/><line x1="8" y1="17" x2="16" y2="17"/></svg>'''

        _active_nav = st.session_state.nav

        with st.expander("Prins", expanded=st.session_state.nav.startswith("prins")):
            c1, c2 = st.columns([1, 6])
            with c1:
                st.markdown(_IG_ICON, unsafe_allow_html=True)
            with c2:
                st.button("Instagram", key="btn_prins_ig", use_container_width=True,
                          on_click=set_nav, args=("prins_instagram",),
                          type="primary" if _active_nav == "prins_instagram" else "secondary")
            c1, c2 = st.columns([1, 6])
            with c1:
                st.markdown(_FB_ICON, unsafe_allow_html=True)
            with c2:
                st.button("Facebook", key="btn_prins_fb", use_container_width=True,
                          on_click=set_nav, args=("prins_facebook",),
                          type="primary" if _active_nav == "prins_facebook" else "secondary")

        with st.expander("Edupet", expanded=st.session_state.nav.startswith("edupet")):
            c1, c2 = st.columns([1, 6])
            with c1:
                st.markdown(_IG_ICON, unsafe_allow_html=True)
            with c2:
                st.button("Instagram", key="btn_edupet_ig", use_container_width=True,
                          on_click=set_nav, args=("edupet_instagram",),
                          type="primary" if _active_nav == "edupet_instagram" else "secondary")
            c1, c2 = st.columns([1, 6])
            with c1:
                st.markdown(_FB_ICON, unsafe_allow_html=True)
            with c2:
                st.button("Facebook", key="btn_edupet_fb", use_container_width=True,
                          on_click=set_nav, args=("edupet_facebook",),
                          type="primary" if _active_nav == "edupet_facebook" else "secondary")

        st.markdown("<hr style='border-color: #1a7a6a; margin: 0.5rem 0;'>",
                    unsafe_allow_html=True)

        c1, c2 = st.columns([1, 6])
        with c1:
            st.markdown(_CSV_ICON, unsafe_allow_html=True)
        with c2:
            st.button("CSV Upload", key="btn_csv", use_container_width=True,
                      on_click=set_nav, args=("csv_upload",))

        # ── Token status ──
        st.markdown("<hr style='border-color: #1a7a6a; margin: 1.5rem 0 0.5rem;'>",
                    unsafe_allow_html=True)

        if _tokens_valid:
            st.markdown("🟢 <span style='font-size:0.75rem; color:#4CAF50;'>API verbonden</span>",
                        unsafe_allow_html=True)
        else:
            st.markdown("🔴 <span style='font-size:0.75rem; color:#e53935;'>Token verlopen</span>",
                        unsafe_allow_html=True)
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
    nav = st.session_state.nav
    if nav == "prins_instagram":
        show_single_channel("instagram", "prins")
    elif nav == "prins_facebook":
        show_single_channel("facebook", "prins")
    elif nav == "edupet_instagram":
        show_single_channel("instagram", "edupet")
    elif nav == "edupet_facebook":
        show_single_channel("facebook", "edupet")
    elif nav == "csv_upload":
        show_upload_tab()


if __name__ == "__main__":
    main()
