# competitors.py
"""Configuratie van concurrenten voor benchmark-monitoring."""

COMPETITORS = {
    "hills": {
        "name": "Hill's Pet Nutrition",
        "fb_slug": "HillsPet",
        "tiktok_username": "hillspet",
        "ig_username": "hillspet",
        "color": "#003DA5",  # Hill's blauw
    },
}

# Inactief: FB-scraper haalt geen recente posts op voor deze pagina's
_INACTIVE = {
    "royalcanin": {
        "name": "Royal Canin",
        "fb_slug": "RoyalCanin",
        "tiktok_username": "royalcanin",
        "ig_username": "royalcanin",
        "color": "#E2001A",
    },
    "eukanuba": {
        "name": "Eukanuba",
        "fb_slug": "Eukanuba",
        "tiktok_username": "eukanuba",
        "ig_username": "eukanuba",
        "color": "#D4A017",
    },
}

# Prins eigen kleuren (voor benchmark charts)
PRINS_COLOR = "#0d5a4d"
EDUPET_COLOR = "#7ab648"

ALL_BRAND_COLORS = {
    "prins": PRINS_COLOR,
    "edupet": EDUPET_COLOR,
    **{key: comp["color"] for key, comp in COMPETITORS.items()},
}
