"""
Thin client around The Odds API (https://the-odds-api.com).
Swap the base URL / parsing logic here if you use a different provider —
everything downstream just expects a list of dicts shaped like the output
of _parse_matches.
"""

import os
import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple

log = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4/sports"

# How long to trust a cached /sports listing before re-checking (this call is
# free / doesn't cost API quota, but no need to hit it on every button tap).
SPORTS_LIST_TTL_SECONDS = 6 * 60 * 60  # 6 hours

# How long to trust a cached odds fetch for one league (this call DOES cost
# quota -- caching here is what keeps "scan every league" affordable).
ODDS_CACHE_TTL_SECONDS = 5 * 60  # 5 minutes


class OddsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ODDS_API_KEY")
        if not self.api_key:
            raise ValueError("Set ODDS_API_KEY as an environment variable or pass api_key explicitly.")

        self._sports_cache: Optional[List[Dict]] = None
        self._sports_cache_time: float = 0
        self._odds_cache: Dict[str, Tuple[float, List[Dict]]] = {}

    # ---------------------------------------------------------------
    # League discovery
    # ---------------------------------------------------------------
    def list_sports(self, force_refresh: bool = False) -> List[Dict]:
        """Raw /sports response. This endpoint does not cost API quota."""
        now = time.time()
        if (not force_refresh and self._sports_cache is not None and
                now - self._sports_cache_time < SPORTS_LIST_TTL_SECONDS):
            return self._sports_cache

        resp = requests.get(BASE_URL, params={"apiKey": self.api_key}, timeout=15)
        resp.raise_for_status()
        self._sports_cache = resp.json()
        self._sports_cache_time = now
        return self._sports_cache

    def get_active_soccer_leagues(self, force_refresh: bool = False) -> List[Dict]:
        """
        Every currently active soccer competition The Odds API covers, as
        {"key": "soccer_epl", "title": "EPL"} dicts -- key is what you pass to
        get_soccer_odds, title is the human-readable league name used for
        league-type classification and display.
        """
        sports = self.list_sports(force_refresh=force_refresh)
        return [
            {"key": s["key"], "title": s.get("title", s["key"])}
            for s in sports
            if s.get("group") == "Soccer" and s.get("active", True)
        ]

    # ---------------------------------------------------------------
    # Odds fetching
    # ---------------------------------------------------------------
    def get_soccer_odds(self, sport_key: str = "soccer_epl", league_title: Optional[str] = None,
                         regions: str = "eu", markets: str = "h2h,totals",
                         use_cache: bool = True) -> List[Dict]:
        """
        Fetch odds for a given soccer competition. Cached for ODDS_CACHE_TTL_SECONDS
        so repeated button taps within a few minutes don't re-spend API quota.

        sport_key examples: soccer_epl, soccer_spain_la_liga, soccer_germany_bundesliga,
        soccer_brazil_campeonato, soccer_mexico_ligamx ... see get_active_soccer_leagues()
        for the full live list.
        """
        cache_key = f"{sport_key}:{regions}:{markets}"
        if use_cache and cache_key in self._odds_cache:
            cached_at, cached_matches = self._odds_cache[cache_key]
            if time.time() - cached_at < ODDS_CACHE_TTL_SECONDS:
                return cached_matches

        url = f"{BASE_URL}/{sport_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        matches = self._parse_matches(resp.json(), sport_key, league_title)

        self._odds_cache[cache_key] = (time.time(), matches)
        return matches

    def get_matches_in_window(self, sport_keys: Optional[List[str]] = None, hours: int = 12,
                               regions: str = "eu", markets: str = "h2h,totals",
                               all_leagues: bool = False) -> List[Dict]:
        """
        Fetch matches across leagues and keep only those kicking off between
        now and `hours` from now (i.e. "next 12 hours from when I clicked").

        Pass all_leagues=True (or sport_keys=None) to scan every active soccer
        league The Odds API currently covers, discovered via /sports.
        NOTE: each league still costs API quota per odds call -- scanning all
        leagues on every tap will burn a free-tier plan fast. The 5-minute
        odds cache above is what makes repeated taps cheap; the actual quota
        cost is proportional to how many *distinct* leagues have live matches
        each time the cache expires.
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)
        log.info(f"[diag] window is {now.isoformat()} -> {cutoff.isoformat()} ({hours}h)")

        if all_leagues or sport_keys is None:
            leagues = self.get_active_soccer_leagues()
        else:
            leagues = [{"key": k.strip(), "title": None} for k in sport_keys]

        all_matches = []
        for league in leagues:
            try:
                matches = self.get_soccer_odds(
                    sport_key=league["key"], league_title=league.get("title"),
                    regions=regions, markets=markets,
                )
            except requests.exceptions.RequestException as e:
                log.error(f"[diag] [{league['key']}] odds fetch failed: {e}")
                continue

            kickoffs = sorted(m.get("commence_time") for m in matches if m.get("commence_time"))
            log.info(
                f"[diag] [{league['key']}] API returned {len(matches)} match(es) with usable odds; "
                f"kickoff range: {kickoffs[0] if kickoffs else 'n/a'} -> {kickoffs[-1] if kickoffs else 'n/a'}"
            )

            in_window = 0
            for m in matches:
                commence = m.get("commence_time")
                if not commence:
                    continue
                try:
                    kickoff = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if now <= kickoff <= cutoff:
                    all_matches.append(m)
                    in_window += 1
            log.info(f"[diag] [{league['key']}] {in_window}/{len(matches)} match(es) fall inside the {hours}h window")

        all_matches.sort(key=lambda m: m["commence_time"])
        return all_matches

    # ---------------------------------------------------------------
    # Parsing
    # ---------------------------------------------------------------
    def _parse_matches(self, raw_matches: List[Dict], sport_key: str,
                        league_title: Optional[str] = None) -> List[Dict]:
        """
        Normalize The Odds API's response into the flat shape betting_framework expects:
        {league_name, home_team, away_team, commence_time,
         home_odds, draw_odds, away_odds, over_odds, under_odds}

        Note: The Odds API's 'totals' market usually only carries one point line
        (commonly 2.5) per bookmaker — check the 'point' field per outcome if you
        need to select a specific line, and add 3.5 handling if your plan includes it.
        """
        display_league = league_title or sport_key
        parsed = []
        for match in raw_matches:
            home_team = match.get("home_team")
            away_team = match.get("away_team")
            bookmakers = match.get("bookmakers", [])
            if not bookmakers:
                continue

            # Use the first available bookmaker; you may want to average across
            # several, or pick a specific preferred book instead.
            book = bookmakers[0]
            h2h = next((m for m in book["markets"] if m["key"] == "h2h"), None)
            totals = next((m for m in book["markets"] if m["key"] == "totals"), None)

            if not h2h:
                continue

            odds_map = {o["name"]: o["price"] for o in h2h["outcomes"]}
            home_odds = odds_map.get(home_team)
            away_odds = odds_map.get(away_team)
            draw_odds = odds_map.get("Draw")

            over_odds = under_odds = None
            if totals:
                for o in totals["outcomes"]:
                    if o["name"] == "Over":
                        over_odds = o["price"]
                    elif o["name"] == "Under":
                        under_odds = o["price"]

            if not (home_odds and away_odds and draw_odds):
                continue

            parsed.append({
                "league_name": display_league,
                "sport_key": sport_key,
                "home_team": home_team,
                "away_team": away_team,
                "commence_time": match.get("commence_time"),
                "home_odds": home_odds,
                "draw_odds": draw_odds,
                "away_odds": away_odds,
                "over_odds": over_odds,
                "under_odds": under_odds,
            })

        return parsed
