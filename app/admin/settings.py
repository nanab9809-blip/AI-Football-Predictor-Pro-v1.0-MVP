from __future__ import annotations

# Preset liga yang dapat dipilih dari Admin. Filtering memakai League ID
# API-Football agar kompetisi dengan nama serupa tidak tertukar.
TOP_LEAGUE_PRESETS = [
    # Kompetisi internasional Eropa
    {"id": 2, "country": "World", "name": "UEFA Champions League"},
    {"id": 3, "country": "World", "name": "UEFA Europa League"},
    {"id": 848, "country": "World", "name": "UEFA Conference League"},

    # Negara yang diminta pengguna
    {"id": 113, "country": "Sweden", "name": "Allsvenskan"},
    {"id": 114, "country": "Sweden", "name": "Superettan"},

    {"id": 39, "country": "England", "name": "Premier League"},
    {"id": 40, "country": "England", "name": "Championship"},
    {"id": 41, "country": "England", "name": "League One"},
    {"id": 42, "country": "England", "name": "League Two"},

    {"id": 128, "country": "Argentina", "name": "Liga Profesional Argentina"},
    {"id": 129, "country": "Argentina", "name": "Primera Nacional"},

    {"id": 71, "country": "Brazil", "name": "Serie A"},
    {"id": 72, "country": "Brazil", "name": "Serie B"},

    {"id": 119, "country": "Denmark", "name": "Superliga"},
    {"id": 120, "country": "Denmark", "name": "1st Division"},

    {"id": 179, "country": "Scotland", "name": "Premiership"},
    {"id": 180, "country": "Scotland", "name": "Championship"},

    {"id": 103, "country": "Norway", "name": "Eliteserien"},
    {"id": 104, "country": "Norway", "name": "1. Division"},

    {"id": 169, "country": "China", "name": "Super League"},
    {"id": 170, "country": "China", "name": "League One"},

    # Liga top lain yang tetap tersedia
    {"id": 140, "country": "Spain", "name": "La Liga"},
    {"id": 135, "country": "Italy", "name": "Serie A"},
    {"id": 78, "country": "Germany", "name": "Bundesliga"},
    {"id": 61, "country": "France", "name": "Ligue 1"},
    {"id": 88, "country": "Netherlands", "name": "Eredivisie"},
    {"id": 94, "country": "Portugal", "name": "Primeira Liga"},
    {"id": 203, "country": "Turkey", "name": "Super Lig"},
    {"id": 253, "country": "USA", "name": "Major League Soccer"},
    {"id": 307, "country": "Saudi Arabia", "name": "Saudi Pro League"},
    {"id": 98, "country": "Japan", "name": "J1 League"},
]

DEFAULT_TOP_LEAGUE_IDS = [item["id"] for item in TOP_LEAGUE_PRESETS]

DEFAULT_ADMIN_SETTINGS = {
    "min_confidence": 62.0,
    "min_pqi": 60.0,
    "min_ev": 0.03,
    "max_builder_legs": 2,
    "kelly_fraction": 0.25,
    "scanner_limit": 10,
    "scanner_profile": "SAFE",
    "scanner_concurrency": 2,
    "scanner_retry": 2,
    "scanner_delay_seconds": 0.5,
    "scanner_timeout_seconds": 50,
    "scanner_skip_existing": True,
    "scanner_league_filter_mode": "SELECTED",
    "scanner_league_filter_enabled": True,
    "scanner_allowed_league_ids": DEFAULT_TOP_LEAGUE_IDS,
}
