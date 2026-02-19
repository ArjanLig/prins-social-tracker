# app.py
"""Prins Social Tracker — Streamlit Dashboard."""

import os
import tempfile
from datetime import datetime, timezone

import pandas as pd
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

    st.title("Prins Social Tracker")
    password = st.text_input("Wachtwoord", type="password")
    if st.button("Inloggen"):
        if password == st.secrets.get("password", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Onjuist wachtwoord")
    return False


def show_posts_table(platform: str):
    """Render an editable posts table for a platform."""
    posts = get_posts(platform=platform)
    if not posts:
        st.info(f"Nog geen {platform} posts. Upload een CSV via de 'CSV Upload' tab.")
        return

    df = pd.DataFrame(posts)

    # Month filter
    df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")
    df["month_sort"] = df["date_parsed"].dt.to_period("M")
    months = sorted(df["month_sort"].dropna().unique(), reverse=True)
    month_labels = ["Alle"] + [str(m) for m in months]
    selected = st.selectbox("Maand", month_labels, key=f"{platform}_month")

    if selected != "Alle":
        df = df[df["month_sort"].astype(str) == selected]

    # Page filter
    pages = sorted(df["page"].unique())
    if len(pages) > 1:
        selected_page = st.selectbox("Pagina", ["Alle"] + list(pages), key=f"{platform}_page")
        if selected_page != "Alle":
            df = df[df["page"] == selected_page]

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
        key=f"{platform}_editor",
    )

    # Save changes
    if not edited.equals(display_df):
        if st.button("Wijzigingen opslaan", key=f"{platform}_save"):
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


def show_dashboard():
    """Dashboard with KPIs and monthly charts."""
    st.header("Dashboard — Prins Social Tracker")

    stats = get_monthly_stats()
    all_posts = get_posts()

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

    # Monthly trend charts
    if stats:
        df_stats = pd.DataFrame(stats)

        st.subheader("Engagement per maand")
        chart_data = df_stats.pivot_table(
            index="month", columns="platform",
            values="total_engagement", aggfunc="sum"
        ).fillna(0)
        st.bar_chart(chart_data)

        st.subheader("Aantal posts per maand")
        posts_chart = df_stats.pivot_table(
            index="month", columns="platform",
            values="total_posts", aggfunc="sum"
        ).fillna(0)
        st.bar_chart(posts_chart)

        st.subheader("Bereik per maand")
        reach_chart = df_stats.pivot_table(
            index="month", columns="platform",
            values="total_reach", aggfunc="sum"
        ).fillna(0)
        st.bar_chart(reach_chart)


def main():
    if not check_password():
        return

    tab_dashboard, tab_facebook, tab_instagram, tab_upload = st.tabs(
        ["📊 Dashboard", "📘 Facebook Posts", "📸 Instagram Posts", "📤 CSV Upload"]
    )

    with tab_dashboard:
        show_dashboard()

    with tab_facebook:
        st.header("Facebook Posts")
        show_posts_table("facebook")

    with tab_instagram:
        st.header("Instagram Posts")
        show_posts_table("instagram")

    with tab_upload:
        show_upload_tab()


if __name__ == "__main__":
    main()
