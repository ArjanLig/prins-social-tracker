# competitors.py
"""Per-kanaal configuratie van concurrenten voor benchmark-monitoring."""

# ── Facebook concurrenten ──
FB_COMPETITORS = {
    "hills": {
        "name": "Hill's Pet Nutrition",
        "slug": "HillsPet",
        "color": "#003DA5",
    },
    "justrussel": {
        "name": "Just Russel",
        "slug": "DierenvoedingJustRussel",
        "color": "#FF6B35",
    },
    "renske": {
        "name": "Renske",
        "slug": "renskenaturalpetfood",
        "color": "#8B4513",
    },
    "butternutbox": {
        "name": "Butternut Box",
        "slug": "ButternutBox",
        "color": "#F0C808",
    },
    "acana": {
        "name": "Acana",
        "slug": "ACANAPetFoods",
        "color": "#C41E3A",
    },
    "purina": {
        "name": "Purina",
        "slug": "purina",
        "color": "#CC0033",
    },
    "tasteofthewild": {
        "name": "Taste of the Wild",
        "slug": "tasteofthewildpetfood",
        "color": "#2E8B57",
    },
    "riverwood": {
        "name": "Riverwood",
        "slug": "riverwooddiervoeding",
        "color": "#4682B4",
    },
    "carocroc": {
        "name": "CaroCroc",
        "slug": "CaroCroc",
        "color": "#E67E22",
    },
    "orijen": {
        "name": "Orijen",
        "slug": "ORIJENPetFoods",
        "color": "#6B2D5B",
    },
    "wooof": {
        "name": "Wooof",
        "slug": "Wooofdogfood",
        "color": "#17A2B8",
    },
    "naturalbalance": {
        "name": "Natural Balance",
        "slug": "naturalbalance",
        "color": "#228B22",
    },
}

# ── Instagram concurrenten ──
IG_COMPETITORS = {
    "edgardcooper": {
        "name": "Edgard & Cooper",
        "username": "edgardcooper",
        "color": "#F4A460",
    },
    "justrussel": {
        "name": "Just Russel",
        "username": "justrussel.nl",
        "color": "#FF6B35",
    },
    "royalcanin": {
        "name": "Royal Canin",
        "username": "royalcanin_nl",
        "color": "#E2001A",
    },
    "butternutbox": {
        "name": "Butternut Box",
        "username": "butternutbox",
        "color": "#F0C808",
    },
    "tasteofthewild": {
        "name": "Taste of the Wild",
        "username": "tasteofthewild",
        "color": "#2E8B57",
    },
    "riverwood": {
        "name": "Riverwood",
        "username": "riverwood_petfood",
        "color": "#4682B4",
    },
    "wooof": {
        "name": "Wooof",
        "username": "wooofnl",
        "color": "#17A2B8",
    },
    "orijen": {
        "name": "Orijen",
        "username": "orijenpetfood",
        "color": "#6B2D5B",
    },
}

# ── TikTok concurrenten ──
TK_COMPETITORS = {
    "edgardcooper": {
        "name": "Edgard & Cooper",
        "username": "edgardcooper",
        "color": "#F4A460",
    },
    "justrussel": {
        "name": "Just Russel",
        "username": "justrussel_com",
        "color": "#FF6B35",
    },
    "butternutbox": {
        "name": "Butternut Box",
        "username": "butternutbox",
        "color": "#F0C808",
    },
    "wooof": {
        "name": "Wooof",
        "username": "wooofhondenvoer",
        "color": "#17A2B8",
    },
    "riverwood": {
        "name": "Riverwood",
        "username": "riverwoodpetfood",
        "color": "#4682B4",
    },
}

# ── Prins eigen kleuren (voor benchmark charts) ──
PRINS_COLOR = "#0d5a4d"
EDUPET_COLOR = "#7ab648"

# ── Gecombineerde naam/kleur lookup voor alle concurrenten ──
ALL_COMPETITORS = {}
for _d in [FB_COMPETITORS, IG_COMPETITORS, TK_COMPETITORS]:
    for _key, _comp in _d.items():
        if _key not in ALL_COMPETITORS:
            ALL_COMPETITORS[_key] = {"name": _comp["name"], "color": _comp["color"]}

ALL_BRAND_COLORS = {
    "prins": PRINS_COLOR,
    "edupet": EDUPET_COLOR,
    **{key: comp["color"] for key, comp in ALL_COMPETITORS.items()},
}


def get_competitor_keys(platform: str) -> list:
    """Return lijst van competitor keys voor een specifiek platform."""
    if platform == "facebook":
        return list(FB_COMPETITORS.keys())
    elif platform == "instagram":
        return list(IG_COMPETITORS.keys())
    elif platform == "tiktok":
        return list(TK_COMPETITORS.keys())
    return []


def get_competitor_name(key: str) -> str:
    """Return display name voor een competitor key."""
    if key == "prins":
        return "Prins Petfoods"
    if key == "edupet":
        return "Edupet"
    comp = ALL_COMPETITORS.get(key)
    return comp["name"] if comp else key.capitalize()


def get_competitor_url(key: str, platform: str) -> str | None:
    """Return social media profiel-URL voor een competitor op een platform."""
    if platform == "facebook":
        if key == "prins":
            return "https://www.facebook.com/PrinsPetfoods"
        if key == "edupet":
            return "https://www.facebook.com/edupet.nl"
        comp = FB_COMPETITORS.get(key)
        return f"https://www.facebook.com/{comp['slug']}" if comp else None
    elif platform == "instagram":
        if key == "prins":
            return "https://www.instagram.com/prinspetfoods/"
        if key == "edupet":
            return "https://www.instagram.com/edupet.nl/"
        comp = IG_COMPETITORS.get(key)
        return f"https://www.instagram.com/{comp['username']}/" if comp else None
    elif platform == "tiktok":
        if key == "prins":
            return "https://www.tiktok.com/@prinspetfoods"
        comp = TK_COMPETITORS.get(key)
        return f"https://www.tiktok.com/@{comp['username']}" if comp else None
    return None
