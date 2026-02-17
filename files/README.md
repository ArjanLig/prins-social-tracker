# Prins Petfoods Social Media Tracker

Geautomatiseerde tool voor het verzamelen en rapporteren van social media statistieken.

## ✅ Wat werkt nu:

- **Facebook volgers tracking** via API
- **Facebook posts data** via CSV import
- **Excel export** met automatische sheets voor Facebook KPIs en Posts
- **Instagram** (voorbereid, maar nog niet actief wegens Meta verificatie)

## 📋 Wat je nodig hebt:

1. **Python 3.8+** (je hebt 3.14)
2. **Facebook Page Access Token**
3. **Facebook CSV export** (gedownload via Meta Business Suite)

## 🚀 Setup

### Stap 1: Installeer dependencies

```bash
cd ~/Documents/prins-social-tracker
pip3 install requests python-dotenv openpyxl pandas --break-system-packages
```

### Stap 2: Configureer environment

```bash
# Kopieer example naar .env
cp .env.example .env

# Edit .env en vul in:
nano .env
```

**Vul in .env:**
- `PRINS_TOKEN` - Page Access Token (zie hieronder)
- `PRINS_CSV_PATH` - Pad naar Facebook CSV export

**Page Access Token genereren:**
1. Ga naar: https://developers.facebook.com/tools/explorer
2. Selecteer "Prins Social Tracker" app
3. Klik "Get Page Access Token" → "Prins Petfoods"
4. Kopieer token → plak in .env

**Facebook CSV exporteren:**
1. Ga naar: https://business.facebook.com
2. Statistieken → Datumbereik selecteren
3. Scroll naar "Populairste contentindelingen" → Exporteren
4. Download CSV → zet pad in .env bij PRINS_CSV_PATH

### Stap 3: Run script

```bash
python3 social_tracker.py
```

## 📊 Output: Social cijfers 2026 PRINS.xlsx

**Facebook KPIs sheet:** Maandelijkse samenvatting (fans, volgers, engagement)  
**Facebook cijfers sheet:** Individuele posts met metrics

## 🔄 Maandelijks gebruik

1. Download nieuwe Facebook CSV (vorige maand)
2. Update `PRINS_CSV_PATH` in .env
3. Run `python3 social_tracker.py`
4. Open Excel en bekijk updated data

## ⚠️ Troubleshooting

**"Ontbrekende environment variabelen"** → Check .env bestand  
**"Geen Facebook CSV gevonden"** → Check PRINS_CSV_PATH pad  
**"400 Bad Request"** → Token verlopen, genereer nieuwe  

## 🔐 Security

- `.env` bevat tokens → NOOIT committen
- Page tokens verlopen na ~60 dagen
- Gebruik Page Access Token, niet User token

---

**Status:** Facebook ✅ | Instagram ⏳ (wacht op Meta verificatie)
