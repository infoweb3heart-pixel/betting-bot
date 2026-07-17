from typing import Dict

FRIENDLY_KEYWORDS = ["friendly", "friendlies"]
YOUTH_KEYWORDS = ["u20", "u21", "u19", "u18", "youth", "reserve", "reserves"]
CUP_KEYWORDS = [
    "champions league", "europa league", "conference league",
    "cup", "copa", "coppa", "pokal", "trophy",
]
WOMENS_KEYWORDS = ["women", "womens", "wsl", "nwsl", "frauen", "feminine", "femenina"]

# Leagues the spec calls out as high-scoring. Matched against the league title.
HIGH_SCORING_LEAGUE_KEYWORDS = [
    "premier league", "epl", "bundesliga", "serie a", "la liga", "eredivisie", "mls",
]


def classify_match(league_key: str, league_title: str, home_team: str, away_team: str) -> Dict[str, bool]:
    """Best-effort classification from league/team name text. the-odds-api
    doesn't expose an explicit 'match type' field, so this is a heuristic —
    it can miss edge cases (e.g. an unlabeled youth tournament)."""
    haystack = f"{league_key} {league_title} {home_team} {away_team}".lower()
    title_lower = league_title.lower()

    return {
        "is_friendly": any(k in haystack for k in FRIENDLY_KEYWORDS),
        "is_youth": any(k in haystack for k in YOUTH_KEYWORDS),
        "is_cup": any(k in haystack for k in CUP_KEYWORDS),
        "is_womens": any(k in haystack for k in WOMENS_KEYWORDS),
        "is_high_scoring_league": any(k in title_lower for k in HIGH_SCORING_LEAGUE_KEYWORDS),
    }
