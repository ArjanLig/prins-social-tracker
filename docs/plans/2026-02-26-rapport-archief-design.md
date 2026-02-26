# Rapport-archief Design

## Doel
Maandrapporten opslaan in de database zodat ze later terug te lezen zijn, en voorkomen dat een rapport opnieuw gegenereerd wordt voor een maand die al bestaat.

## Database
Nieuwe tabel `ai_reports`:
- `id`, `month` (YYYY-MM), `platform` (default "cross"), `page`, `content` (markdown), `created_at`
- UNIQUE constraint op (month, platform, page) — 1 rapport per combinatie

## Database-laag
- `save_report()` — INSERT or REPLACE
- `get_report()` — returns content of None

## UI-flow
1. Selecteer maand
2. Check database voor bestaand rapport
3. Rapport bestaat → toon direct + knop "Opnieuw genereren"
4. Rapport bestaat niet → knop "Genereer rapport"
5. Na genereren → opslaan in database

## Scope
- Alleen maandrapporten (cross-platform en per-platform)
- Chat, analyses en suggesties blijven vluchtig (session_state)
- Bestaande AI-functies ongewijzigd
