# Design Redesign: Clean & Modern

## Approach
Theme-first refactor — move all styling from ~240 lines of fragile CSS to `config.toml` theming + native Streamlit components.

## Theme (config.toml)
- Prins green (#0d5a4d) as primary
- Inter font via Google Fonts
- Light sidebar (#f7f8fa), no border
- 12px base radius, pill buttons
- Chart colors: green palette + accent colors

## Changes

### Remove
- All `st.markdown("<style>...")` blocks (~240 lines CSS)
- Inline HTML headers, dividers, SVG icons
- Base64 logo encoding
- Custom loading spinner CSS

### Replace with
- `st.logo()` for sidebar logo
- Material icons for platform icons
- Native `st.header()` / `st.subheader()` for titles
- `st.badge()` for status indicators
- `st.space()` instead of `<hr>` dividers
- `st.container(border=True)` for visual grouping
- Native metric cards (no CSS override)

### Keep unchanged
- All functionality
- Navigation structure (Prins/Edupet expanders)
- Plotly charts (update color scheme only)
- Data tables
- AI Inzichten page (visual only)
