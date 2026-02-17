# CSV Import Design — Prins Social Tracker

## Doel

Overstappen van scraper-first naar CSV-import als primaire databron voor Facebook en Instagram posts. De scraper blijft beschikbaar voor aanvullende data en toekomstige concurrentie-analyse.

## Platformen

- Prins Petfoods Facebook
- Prins Petfoods Instagram
- Edupet Facebook

## Flow

1. Gebruiker geeft een map op: `python3 fetch_stats.py /pad/naar/csv-map/`
2. Script scant de map op CSV-bestanden
3. Herkent automatisch welk type CSV het is (FB Prins, FB Edupet, IG Prins) op basis van inhoud/kolomnamen
4. Importeert de data naar Excel met maandkleuren
5. Scraper vult ontbrekende info aan (bijv. posts zonder engagement data)

## CSV-herkenning

Meta Business Suite exporteert per pagina. Kolomnamen zijn in het Nederlands.

- **Facebook CSV** — bevat kolommen als "Bereik", "Deelacties", "Berichttype"
- **Instagram CSV** — bevat kolommen als "Vind-ik-leuks", "Media type"

De paginanaam staat vaak in de CSV of filename. Het script probeert automatisch te matchen, en vraagt bij twijfel welke pagina het is.

## Kolomnamen mapping

Flexibele mapping die meerdere varianten accepteert:

| Intern veld | Mogelijke CSV-kolommen                        |
|-------------|-----------------------------------------------|
| datum       | Publicatietijdstip, Datum, Date               |
| type        | Berichttype, Type, Media type                 |
| tekst       | Titel, Bericht, Caption                       |
| bereik      | Bereik, Reach                                 |
| weergaven   | Weergaven, Impressions, Views                 |
| likes       | Reacties, Likes, Vind-ik-leuks                |
| reacties    | Opmerkingen, Comments                         |
| shares      | Deelacties, Shares                            |
| klikken     | Totaal aantal klikken, Clicks                 |

## Scraper als aanvulling

Na CSV-import checkt het script of er posts zijn zonder bepaalde velden. Als de scraper sessie beschikbaar is, vult het die aan.

## Voorbereiding op app

De CSV-parseerlogica wordt een losse functie (`parse_csv_folder(path)`) zodat die later vanuit een web-app aangeroepen kan worden.

## Beslissingen

- Scraper behouden voor concurrentie-analyse en aanvullen van ontbrekende data
- CSV-map via command line argument (drag & drop), later via web-app upload
- Automatische herkenning van CSV-type (platform + pagina)
