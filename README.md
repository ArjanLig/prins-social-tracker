# Prins Petfoods Social Media Tracker

Geautomatiseerde tool voor het verzamelen en rapporteren van social media statistieken.

## Wat werkt nu:

- **Facebook & Instagram posts** via CSV import (Meta Business Suite)
- **Facebook volgers tracking** via API
- **Facebook posts scraping** via Playwright (als aanvulling op CSV)
- **Excel export** met maandkleuren, KPI's en post-details
- **AI analyse** via OpenAI GPT-4o-mini
- **Instagram** (voorbereid, actief via CSV import)

## Setup

### Stap 1: Installeer dependencies

```bash
cd ~/Documents/github/prins-social-tracker
pip3 install -r requirements.txt --break-system-packages
```

### Stap 2: Configureer environment

```bash
cp files/.env.example .env
nano .env
```

Vul in `.env`:
- `PRINS_TOKEN` - Page Access Token
- `EDUPET_TOKEN` - Edupet Page Access Token
- `PRINS_PAGE_ID` / `EDUPET_PAGE_ID` - Facebook Page ID's
- `OPENAI_API_KEY` - Voor AI analyse (optioneel)

## Gebruik

### CSV Import (aanbevolen)

1. Exporteer posts vanuit [Meta Business Suite](https://business.facebook.com) als CSV
2. Zet alle CSV-bestanden in een map
3. Draai:

```bash
python3 fetch_stats.py --csv /pad/naar/csv-map/
```

Het script herkent automatisch of een CSV Facebook of Instagram data bevat.
Zet "edupet" in de bestandsnaam voor Edupet-data (bijv. `edupet_fb.csv`).

### Scraper + API (alternatief)

```bash
# Eerste keer: log in op Facebook
python3 fb_scraper.py --login

# Daarna: data ophalen via scraper + API
python3 fetch_stats.py
```

### Opties

| Optie | Beschrijving |
|---|---|
| `--csv MAP` | Map met CSV exports uit Meta Business Suite |
| `--no-analysis` | Sla de AI-analyse over |

## Output: Social cijfers 2026 PRINS.xlsx

| Sheet | Inhoud |
|---|---|
| **Facebook KPIs** | Maandelijkse samenvatting (fans, volgers, engagement) |
| **Facebook cijfers** | Individuele posts met metrics + maandkleuren |
| **Instagram KPI's** | Maandelijkse Instagram metrics |
| **Instagram cijfers** | Individuele IG posts met metrics + maandkleuren |
| **AI Analyse** | Gegenereerde analyse en aanbevelingen |

Posts worden automatisch per maand gegroepeerd met afwisselende pastelkleuren.

## Troubleshooting

**"Ontbrekende environment variabelen"** — Check .env bestand
**"400 Bad Request"** — Token verlopen, genereer nieuwe via [Graph API Explorer](https://developers.facebook.com/tools/explorer)
**"Geen Facebook-sessie"** — Draai eerst `python3 fb_scraper.py --login`

## Security

- `.env` bevat tokens — NOOIT committen
- Page tokens verlopen na ~60 dagen
