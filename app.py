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

st.set_page_config(
    page_title="Prins Social Tracker",
    page_icon="📊",
    layout="wide",
)

# Init database on startup
init_db()

# ── Meta Graph API ──
FB_API_VERSION = "v21.0"
FB_BASE_URL = f"https://graph.facebook.com/{FB_API_VERSION}"

BRAND_CONFIG = {
    "prins": {
        "token": os.getenv("PRINS_TOKEN"),
        "page_id": os.getenv("PRINS_PAGE_ID"),
    },
    "edupet": {
        "token": os.getenv("EDUPET_TOKEN"),
        "page_id": os.getenv("EDUPET_PAGE_ID"),
    },
}


@st.cache_data(ttl=3600)
def fetch_follower_counts(brand: str) -> dict | None:
    """Haal volgers op voor Facebook en Instagram via de Graph API."""
    config = BRAND_CONFIG.get(brand)
    if not config:
        return None

    token = config.get("token")
    page_id = config.get("page_id")
    if not token or not page_id:
        return None

    result = {"facebook": None, "instagram": None}

    # Facebook followers
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}",
            params={"fields": "followers_count,fan_count", "access_token": token},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        result["facebook"] = data.get("followers_count") or data.get("fan_count")
    except Exception:
        pass

    # Instagram followers via gekoppeld business account
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}",
            params={"fields": "instagram_business_account{followers_count}",
                    "access_token": token},
            timeout=15,
        )
        resp.raise_for_status()
        ig_data = resp.json()
        ig_account = ig_data.get("instagram_business_account", {})
        result["instagram"] = ig_account.get("followers_count")
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

    # Facebook posts
    try:
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}/published_posts",
            params={
                "fields": "message,created_time,shares,"
                          "likes.summary(true),comments.summary(true),"
                          "insights.metric(post_impressions_unique)",
                "limit": 50,
                "access_token": token,
            },
            timeout=30,
        )
        resp.raise_for_status()
        fb_posts = []
        for post in resp.json().get("data", []):
            likes = post.get("likes", {}).get("summary", {}).get("total_count", 0)
            comments = post.get("comments", {}).get("summary", {}).get("total_count", 0)
            shares = post.get("shares", {}).get("count", 0)
            reach = 0
            for ins in post.get("insights", {}).get("data", []):
                if ins["name"] == "post_impressions_unique":
                    reach = ins["values"][0]["value"]
            fb_posts.append({
                "date": post.get("created_time", ""),
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
        if fb_posts:
            result["facebook"] = insert_posts(DEFAULT_DB, fb_posts, "facebook")
    except Exception:
        pass

    # Instagram posts
    try:
        # Haal IG business account ID op
        resp = requests.get(
            f"{FB_BASE_URL}/{page_id}",
            params={"fields": "instagram_business_account",
                    "access_token": token},
            timeout=15,
        )
        resp.raise_for_status()
        ig_id = resp.json().get("instagram_business_account", {}).get("id")
        if ig_id:
            resp = requests.get(
                f"{FB_BASE_URL}/{ig_id}/media",
                params={
                    "fields": "caption,timestamp,like_count,comments_count,"
                              "media_type,insights.metric(reach)",
                    "limit": 50,
                    "access_token": token,
                },
                timeout=30,
            )
            resp.raise_for_status()
            ig_posts = []
            for post in resp.json().get("data", []):
                reach = 0
                for ins in post.get("insights", {}).get("data", []):
                    if ins["name"] == "reach":
                        reach = ins["values"][0]["value"]
                ig_posts.append({
                    "date": post.get("timestamp", ""),
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
            if ig_posts:
                result["instagram"] = insert_posts(DEFAULT_DB, ig_posts, "instagram")
    except Exception:
        pass

    return result


# ── Prins Petfoods huisstijl CSS ──
st.markdown("""
<style>
    /* Import font similar to Prins website */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* Global font */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Header bar */
    header[data-testid="stHeader"] {
        background-color: #0d5a4d;
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background-color: #ecf3f1;
        border: 1px solid #a2c4ba;
        border-radius: 0.625rem;
        padding: 1rem;
    }
    [data-testid="stMetricLabel"] {
        color: #0d5a4d;
        font-weight: 600;
    }
    [data-testid="stMetricValue"] {
        color: #0d5a4d;
        font-weight: 700;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 2px solid #a2c4ba;
    }
    .stTabs [data-baseweb="tab"] {
        color: #0d5a4d;
        font-weight: 500;
        padding: 0.75rem 1.25rem;
        border-radius: 0.625rem 0.625rem 0 0;
    }
    .stTabs [aria-selected="true"] {
        background-color: #ecf3f1;
        border-top: 3px solid #0d5a4d;
        font-weight: 700;
    }

    /* Buttons */
    .stButton > button {
        background-color: #0d5a4d;
        color: white;
        border: none;
        border-radius: 0.625rem;
        font-weight: 600;
        padding: 0.5rem 1.5rem;
    }
    .stButton > button:hover {
        background-color: #0a4a3f;
        color: white;
    }

    /* Selectbox */
    [data-baseweb="select"] {
        border-radius: 0.625rem;
    }

    /* Data editor / table */
    [data-testid="stDataFrame"] {
        border: 1px solid #a2c4ba;
        border-radius: 0.625rem;
    }

    /* Headers */
    h1, h2, h3 {
        color: #0d5a4d !important;
        font-weight: 700;
    }

    /* Success messages */
    .stSuccess {
        background-color: #ecf3f1;
        border-left-color: #0d5a4d;
    }

    /* Login page centering */
    .login-container {
        max-width: 400px;
        margin: 4rem auto;
        padding: 2rem;
        background: #ecf3f1;
        border-radius: 0.625rem;
        border: 1px solid #a2c4ba;
    }

    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: #0d5a4d;
    }
    [data-testid="stSidebar"] * {
        color: white;
    }

    /* Sidebar expanders */
    [data-testid="stSidebar"] .streamlit-expanderHeader {
        background-color: rgba(255,255,255,0.08);
        border-radius: 0.625rem;
        color: white;
    }
    [data-testid="stSidebar"] .streamlit-expanderHeader:hover {
        background-color: rgba(255,255,255,0.15);
    }
    [data-testid="stSidebar"] .streamlit-expanderContent {
        background-color: transparent;
        border: none;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background-color: transparent;
        border: none !important;
        box-shadow: none !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] details {
        background-color: transparent;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        background-color: rgba(255,255,255,0.08);
        border-radius: 0.625rem;
        color: white;
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
        background-color: rgba(255,255,255,0.15);
    }
    [data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
        background-color: transparent;
        border: none;
    }
    /* Sidebar buttons */
    [data-testid="stSidebar"] .stButton > button {
        background-color: rgba(255,255,255,0.05);
        color: white;
        border: none;
        text-align: left;
        font-weight: 500;
    }
    [data-testid="stSidebar"] .stButton > button:hover {
        background-color: rgba(255,255,255,0.15);
        color: white;
    }

    /* Caption text */
    .stCaption {
        color: #5a7a73;
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
            <h1 style="color: #0d5a4d; margin-bottom: 0.25rem;">Prins Social Tracker</h1>
            <p style="color: #5a7a73; font-size: 1.1rem;">Social media dashboard</p>
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
        <h2 style="color: #0d5a4d; margin-bottom: 0.25rem;">{label}</h2>
        <p style="color: #5a7a73;">Facebook &amp; Instagram overzicht</p>
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

    # KPI cards
    # Volgers via API
    followers = fetch_follower_counts(page)
    follower_count = followers.get(platform) if followers else None

    # Sla snapshot op en bereken groei
    follower_delta = None
    if follower_count is not None:
        save_follower_snapshot(DEFAULT_DB, platform, page, follower_count)
        prev = get_follower_previous_month(DEFAULT_DB, platform, page)
        if prev is not None:
            follower_delta = follower_count - prev

    col1, col2, col3, col4, col5 = st.columns(5)
    if follower_count is not None:
        col1.metric("Volgers", f"{follower_count:,}",
                     delta=f"{follower_delta:+,}" if follower_delta is not None else None)
    else:
        col1.metric("Volgers", "–")
    col2.metric("Posts deze maand", len(df_month))
    col3.metric("Totaal engagement", f"{df_month['engagement'].sum():,}")
    reach_val = df_month['reach'].mean() if len(df_month) > 0 else 0
    col4.metric("Gem. bereik", f"{reach_val:,.0f}" if pd.notna(reach_val) else "0")
    col5.metric("Totaal posts", len(df_all))

    # Monthly trend line charts per jaar
    df_all["year"] = df_all["date_parsed"].dt.year
    df_all["month_num"] = df_all["date_parsed"].dt.month

    available_years = sorted(df_all["year"].dropna().unique().astype(int), reverse=True)
    if not available_years:
        return

    key_prefix = f"{page}_{platform}"
    MONTH_LABELS = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun",
                    "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]
    YEAR_COLORS = ["#0d5a4d", "#a2c4ba", "#e8a87c", "#7c9eb2", "#c4a2d4"]

    selected_years = st.multiselect(
        "Jaren vergelijken",
        options=available_years,
        default=[available_years[0]],
        key=f"{key_prefix}_years",
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
        )
        by_month = by_month.reindex(range(1, 13))
        yearly_data[year] = by_month

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

    def year_line_chart(metric, title):
        fig = go.Figure()
        for i, year in enumerate(sorted(selected_years)):
            color = YEAR_COLORS[i % len(YEAR_COLORS)]
            values = yearly_data[year][metric]
            fig.add_trace(go.Scatter(
                x=list(range(1, 13)), y=values,
                name=str(year),
                mode="lines+markers",
                line=dict(color=color, width=2.5),
                marker=dict(color=color, size=7),
                hovertemplate="%{text}: %{y:,.0f}<extra></extra>",
                text=[f"{MONTH_LABELS[m-1]} {year}" for m in range(1, 13)],
            ))
        fig.update_layout(
            title=dict(text=title, font=dict(size=14, color="#0d5a4d")),
            **layout_base,
        )
        return fig

    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(year_line_chart("engagement", "Engagement per maand"),
                        use_container_width=True)
    with col_b:
        st.plotly_chart(year_line_chart("bereik", "Bereik per maand"),
                        use_container_width=True)

    col_c, col_d = st.columns(2)
    with col_c:
        st.plotly_chart(year_line_chart("likes", "Likes per maand"),
                        use_container_width=True)
    with col_d:
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
        <h2 style="color: #0d5a4d; margin-bottom: 0.25rem;">Dashboard</h2>
        <p style="color: #5a7a73;">{subtitle}</p>
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
            YEAR_COLORS = ["#0d5a4d", "#a2c4ba", "#e8a87c", "#7c9eb2", "#c4a2d4"]

            df_stats["month_parsed"] = pd.to_datetime(df_stats["month"])
            df_stats["year"] = df_stats["month_parsed"].dt.year
            df_stats["month_num"] = df_stats["month_parsed"].dt.month

            available_years = sorted(df_stats["year"].unique().astype(int), reverse=True)

            selected_years = st.multiselect(
                "Jaren vergelijken",
                options=available_years,
                default=[available_years[0]],
                key="dashboard_years",
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

    label = page.capitalize()
    plat_label = platform.capitalize()
    st.markdown(f"""
    <div style="padding: 0.5rem 0 1rem;">
        <h2 style="color: #0d5a4d; margin-bottom: 0.25rem;">{label} — {plat_label}</h2>
        <p style="color: #5a7a73;">{plat_label} overzicht</p>
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
        st.markdown("""
        <div style="text-align: center; padding: 1.5rem 0 1rem;">
            <h2 style="color: white; margin: 0;">Prins</h2>
            <p style="color: #a2c4ba; font-size: 0.85rem; margin: 0;">Social Tracker</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<hr style='border-color: #1a7a6a; margin: 0.5rem 0;'>",
                    unsafe_allow_html=True)

        with st.expander("Prins", expanded=st.session_state.nav.startswith("prins")):
            st.button("Instagram", key="btn_prins_ig", use_container_width=True,
                      on_click=set_nav, args=("prins_instagram",))
            st.button("Facebook", key="btn_prins_fb", use_container_width=True,
                      on_click=set_nav, args=("prins_facebook",))

        with st.expander("Edupet", expanded=st.session_state.nav.startswith("edupet")):
            st.button("Instagram", key="btn_edupet_ig", use_container_width=True,
                      on_click=set_nav, args=("edupet_instagram",))
            st.button("Facebook", key="btn_edupet_fb", use_container_width=True,
                      on_click=set_nav, args=("edupet_facebook",))

        st.markdown("<hr style='border-color: #1a7a6a; margin: 0.5rem 0;'>",
                    unsafe_allow_html=True)

        st.button("CSV Upload", key="btn_csv", use_container_width=True,
                  on_click=set_nav, args=("csv_upload",))

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
