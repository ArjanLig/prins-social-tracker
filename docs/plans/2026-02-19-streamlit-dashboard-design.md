# Streamlit Dashboard — Prins Social Tracker

**Datum:** 2026-02-19
**Status:** Approved

## Doel

Social media cijfers voor Prins Petfoods & Edupet beschikbaar maken voor het hele team via een webdashboard, in plaats van een gedeeld Excel bestand.

## Vereisten

- **Lezen + beperkt bewerken**: collega's bekijken cijfers en kunnen thema/campagne labels toevoegen
- **Klein team (5-15), ook extern bereikbaar**: moet werken buiten kantoor
- **CSV upload via de website**: iedereen kan data toevoegen
- **AI analyse**: later toevoegen, niet in v1
- **Gratis hosting**

## Technologie

- **Streamlit** — Python-based web framework
- **SQLite** — data opslag
- **Streamlit Community Cloud** — gratis hosting (gekoppeld aan GitHub repo)
- **csv_import.py** — bestaande CSV parser hergebruiken

## Architectuur

```
Streamlit Cloud
├── app.py           — Streamlit app (alle pagina's)
├── database.py      — SQLite opslag + query functies
├── csv_import.py    — Bestaande CSV parser (hergebruikt)
└── social_tracker.db — SQLite database
```

## Pagina's

| Tab | Inhoud |
|-----|--------|
| Dashboard | KPI-kaarten (volgers, engagement, posts deze maand) + trendgrafieken per maand |
| Facebook Posts | Tabel met alle FB posts (Prins + Edupet), filterable op maand/pagina. Bewerkbaar: thema en campagne |
| Instagram Posts | Zelfde als FB maar voor IG posts |
| CSV Upload | CSV bestanden uploaden. Auto-detectie FB/IG |

## Database schema

### posts
| Kolom | Type | Beschrijving |
|-------|------|-------------|
| id | INTEGER PK | Auto-increment |
| platform | TEXT | "facebook" of "instagram" |
| page | TEXT | "prins" of "edupet" |
| post_id | TEXT UNIQUE | Deduplicatie key |
| date | TEXT | ISO datum |
| type | TEXT | Post type (Photo, Video, Reel, etc.) |
| text | TEXT | Post tekst/caption |
| reach | INTEGER | Bereik |
| impressions | INTEGER | Weergaven |
| likes | INTEGER | Likes |
| comments | INTEGER | Reacties |
| shares | INTEGER | Shares |
| clicks | INTEGER | Klikken |
| engagement | INTEGER | Totaal engagement |
| engagement_rate | REAL | ER percentage |
| theme | TEXT | Thema (bewerkbaar door team) |
| campaign | TEXT | Campagne (bewerkbaar door team) |
| source_file | TEXT | Bron CSV bestand |
| created_at | TEXT | Timestamp van import |

### kpis
| Kolom | Type | Beschrijving |
|-------|------|-------------|
| id | INTEGER PK | Auto-increment |
| platform | TEXT | "facebook" of "instagram" |
| page | TEXT | "prins" of "edupet" |
| month | TEXT | "2026-01" formaat |
| fans | INTEGER | Aantal fans |
| followers | INTEGER | Aantal volgers |
| total_engagement | INTEGER | Totaal engagement die maand |
| total_posts | INTEGER | Aantal posts die maand |

### uploads
| Kolom | Type | Beschrijving |
|-------|------|-------------|
| id | INTEGER PK | Auto-increment |
| filename | TEXT | Naam van geüpload bestand |
| platform | TEXT | Gedetecteerd platform |
| post_count | INTEGER | Aantal posts geïmporteerd |
| uploaded_at | TEXT | Timestamp |

## Authenticatie

Simpel gedeeld wachtwoord via `st.secrets` (voldoende voor klein intern team). Later upgraden naar SSO indien nodig.

## Bewerkbare velden

Via `st.data_editor` kunnen collega's **thema** en **campagne** toevoegen aan posts. Wijzigingen worden direct opgeslagen in SQLite.
