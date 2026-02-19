# app.py
"""Prins Social Tracker — Streamlit Dashboard."""

import os
import tempfile
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from csv_import import detect_platform, parse_csv_file
from database import (
    DEFAULT_DB,
    get_monthly_stats,
    get_posts,
    get_uploads,
    init_db,
    insert_posts,
    log_upload,
    update_post_labels,
)

st.set_page_config(
    page_title="Prins Social Tracker",
    page_icon="📊",
    layout="wide",
)

# Init database on startup
init_db()

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

    /* Sidebar radio as nav buttons */
    [data-testid="stSidebar"] [role="radiogroup"] {
        gap: 0.25rem;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label {
        background-color: rgba(255,255,255,0.08);
        border-radius: 0.625rem;
        padding: 0.6rem 1rem;
        cursor: pointer;
        transition: background-color 0.2s;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label:hover {
        background-color: rgba(255,255,255,0.15);
    }
    [data-testid="stSidebar"] [role="radiogroup"] label[data-checked="true"],
    [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
        background-color: rgba(255,255,255,0.2);
        font-weight: 700;
    }
    /* Hide radio circles */
    [data-testid="stSidebar"] [role="radiogroup"] input[type="radio"] {
        display: none;
    }
    [data-testid="stSidebar"] [role="radiogroup"] label div[data-testid="stMarkdownContainer"] {
        font-size: 0.95rem;
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


def check_password() -> bool:
    """Simple password gate."""
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
    """Render an editable posts table for a platform + page combo."""
    key_prefix = f"{page}_{platform}"
    posts = get_posts(platform=platform, page=page)
    if not posts:
        st.info(f"Nog geen {platform} posts. Upload een CSV via 'CSV Upload'.")
        return

    df = pd.DataFrame(posts)

    # Month filter
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")
    df["month_sort"] = df["date_parsed"].dt.to_period("M")
    months = sorted(df["month_sort"].dropna().unique(), reverse=True)
    month_labels = ["Alle"] + [str(m) for m in months]
    selected = st.selectbox("Maand", month_labels, key=f"{key_prefix}_month")

    if selected != "Alle":
        df = df[df["month_sort"].astype(str) == selected]

    # Display columns
    display_cols = ["date", "type", "text", "reach", "impressions", "likes",
                    "comments", "shares", "clicks", "engagement",
                    "engagement_rate", "theme", "campaign"]
    col_labels = {
        "date": "Datum", "type": "Type", "text": "Omschrijving",
        "reach": "Bereik", "impressions": "Weergaven", "likes": "Likes",
        "comments": "Reacties", "shares": "Shares", "clicks": "Klikken",
        "engagement": "Engagement", "engagement_rate": "ER%",
        "theme": "Thema", "campaign": "Campagne",
    }

    display_df = df[["id"] + display_cols].copy()
    display_df = display_df.rename(columns=col_labels)

    # Editable table
    edited = st.data_editor(
        display_df,
        disabled=[c for c in display_df.columns if c not in ("Thema", "Campagne")],
        hide_index=True,
        use_container_width=True,
        key=f"{key_prefix}_editor",
    )

    # Save changes
    if not edited.equals(display_df):
        if st.button("Wijzigingen opslaan", key=f"{key_prefix}_save"):
            for idx in range(len(edited)):
                row = edited.iloc[idx]
                orig_row = display_df.iloc[idx] if idx < len(display_df) else None
                if orig_row is not None:
                    if row["Thema"] != orig_row["Thema"] or row["Campagne"] != orig_row["Campagne"]:
                        theme_val = row["Thema"] if pd.notna(row["Thema"]) else ""
                        campaign_val = row["Campagne"] if pd.notna(row["Campagne"]) else ""
                        update_post_labels(DEFAULT_DB, int(row["id"]), theme_val, campaign_val)
            st.success("Labels opgeslagen!")

    # Summary metrics
    st.caption(f"{len(df)} posts | Totaal engagement: {df['engagement'].sum():,} | "
               f"Gem. bereik: {df['reach'].mean():,.0f}")


def show_brand_page(page: str):
    """Show Facebook + Instagram tabs for a specific brand."""
    label = page.capitalize()
    st.markdown(f"""
    <div style="padding: 0.5rem 0 1rem;">
        <h2 style="color: #0d5a4d; margin-bottom: 0.25rem;">{label}</h2>
        <p style="color: #5a7a73;">Facebook &amp; Instagram overzicht</p>
    </div>
    """, unsafe_allow_html=True)

    tab_fb, tab_ig = st.tabs(["Facebook", "Instagram"])

    with tab_fb:
        show_posts_table("facebook", page)

    with tab_ig:
        show_posts_table("instagram", page)


def show_upload_tab():
    """CSV Upload tab."""
    st.header("CSV Upload")
    st.write("Upload CSV-exports uit Meta Business Suite. "
             "Het platform (Facebook/Instagram) wordt automatisch gedetecteerd.")

    page = st.selectbox("Pagina", ["prins", "edupet"], key="upload_page")

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
                    count = insert_posts(DEFAULT_DB, posts, platform=platform, page=page)
                    log_upload(DEFAULT_DB, uf.name, platform, page, count)
                    total_new += count
                    st.success(f"✓ {uf.name}: {count} nieuwe {platform} posts geïmporteerd")
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


def show_dashboard(page: str | None = None):
    """Dashboard with KPIs and monthly charts, optionally filtered by page."""
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

    # Monthly trend charts — filter stats by page if needed
    if stats:
        df_stats = pd.DataFrame(stats)
        if page:
            df_stats = df_stats[df_stats["page"] == page]

        if not df_stats.empty:
            PRINS_COLORS = {
                "facebook": "#0d5a4d",   # donker teal
                "instagram": "#a2c4ba",  # sage groen
            }
            PRINS_LAYOUT = dict(
                font=dict(family="Inter, sans-serif", color="#0d5a4d"),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                legend=dict(
                    orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1, font=dict(size=13),
                ),
                margin=dict(l=20, r=20, t=40, b=40),
                xaxis=dict(gridcolor="#e0ece9", title=None),
                yaxis=dict(gridcolor="#e0ece9", title=None),
                bargap=0.3,
            )

            def prins_bar_chart(df_pivot, title):
                fig = go.Figure()
                for col in df_pivot.columns:
                    fig.add_trace(go.Bar(
                        x=df_pivot.index,
                        y=df_pivot[col],
                        name=col.capitalize(),
                        marker_color=PRINS_COLORS.get(col, "#0d5a4d"),
                        marker_line=dict(width=0),
                        hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
                    ))
                fig.update_layout(
                    title=dict(text=title, font=dict(size=16, color="#0d5a4d")),
                    barmode="group",
                    **PRINS_LAYOUT,
                )
                return fig

            chart_data = df_stats.pivot_table(
                index="month", columns="platform",
                values="total_engagement", aggfunc="sum"
            ).fillna(0)
            st.plotly_chart(prins_bar_chart(chart_data, "Engagement per maand"),
                            use_container_width=True)

            posts_chart = df_stats.pivot_table(
                index="month", columns="platform",
                values="total_posts", aggfunc="sum"
            ).fillna(0)
            st.plotly_chart(prins_bar_chart(posts_chart, "Aantal posts per maand"),
                            use_container_width=True)

            reach_chart = df_stats.pivot_table(
                index="month", columns="platform",
                values="total_reach", aggfunc="sum"
            ).fillna(0)
            st.plotly_chart(prins_bar_chart(reach_chart, "Bereik per maand"),
                            use_container_width=True)


def main():
    if not check_password():
        return

    # ── Sidebar navigatie ──
    with st.sidebar:
        st.markdown("""
        <div style="text-align: center; padding: 1.5rem 0 1rem;">
            <h2 style="color: white; margin: 0;">Prins</h2>
            <p style="color: #a2c4ba; font-size: 0.85rem; margin: 0;">Social Tracker</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<hr style='border-color: #1a7a6a; margin: 0.5rem 0;'>",
                    unsafe_allow_html=True)

        nav = st.radio(
            "Navigatie",
            ["Dashboard", "Prins", "Edupet", "CSV Upload"],
            label_visibility="collapsed",
        )

        st.markdown("<hr style='border-color: #1a7a6a; margin: 0.5rem 0;'>",
                    unsafe_allow_html=True)

        # Upload shortcut info
        st.markdown("""
        <div style="padding: 0.5rem 0; font-size: 0.8rem; color: #a2c4ba;">
            Upload CSV's via<br><b>CSV Upload</b>
        </div>
        """, unsafe_allow_html=True)

    # ── Content ──
    if nav == "Dashboard":
        show_dashboard()
    elif nav == "Prins":
        show_brand_page("prins")
    elif nav == "Edupet":
        show_brand_page("edupet")
    elif nav == "CSV Upload":
        show_upload_tab()


if __name__ == "__main__":
    main()
