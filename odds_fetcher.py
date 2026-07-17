import time
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict

import requests

from config import (
    ODDS_API_KEY,
    ODDS_API_BASE_URL,
    ODDS_API_REGIONS,
    ODDS_API_MARKETS,
    ODDS_API_ODDS_FORMAT,
    LEAGUE_LIST_CACHE_SECONDS,
    MATCHES_CACHE_SECONDS,
    MATCH_WINDOW_HOURS,
)

logger = logging.getLogger(__name__)


class OddsAPIError(Exception):
    """Raised when the-odds-api can't be reached or rejects our key/request."""


class OddsFetcher:
    def __init__(self):
        self.api_key = ODDS_API_KEY
        self.base_url = ODDS_API_BASE_URL

        self._league_cache: List[Dict] = []
        self._league_cache_time: float = 0.0

        self._matches_cache: List[Dict] = []
        self._matches_cache_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_todays_matches(self, force_refresh: bool = False) -> List[Dict]:
        """Return real matches (with odds) for all active soccer leagues,
        starting within MATCH_WINDOW_HOURS from now. Raises OddsAPIError on
        a hard failure (bad key, network down, etc). Returns [] if the API
        is reachable but there's genuinely nothing on today."""

        if not force_refresh and self._matches_cache and \
                (time.time() - self._matches_cache_time) < MATCHES_CACHE_SECONDS:
            return self._matches_cache

        leagues = self._get_active_soccer_leagues(force_refresh=force_refresh)
        if not leagues:
            raise OddsAPIError("Could not retrieve the list of active soccer leagues from the-odds-api.")

        all_matches: List[Dict] = []
        errors = 0

        for league_key in leagues:
            try:
                all_matches.extend(self._fetch_league(league_key))
            except OddsAPIError as e:
                errors += 1
                logger.warning("Skipping league %s: %s", league_key, e)

        if errors == len(leagues):
            raise OddsAPIError(
                "Every league request failed — check your ODDS_API_KEY and remaining quota."
            )

        self._matches_cache = all_matches
        self._matches_cache_time = time.time()
        return all_matches

    def get_active_leagues(self) -> List[Dict]:
        """Returns raw league info (key + human title) for display, e.g. in /leagues."""
        keys = self._get_active_soccer_leagues()
        return [{"key": k, "title": k.replace("_", " ").title()} for k in keys]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_active_soccer_leagues(self, force_refresh: bool = False) -> List[str]:
        if not force_refresh and self._league_cache and \
                (time.time() - self._league_cache_time) < LEAGUE_LIST_CACHE_SECONDS:
            return self._league_cache

        url = f"{self.base_url}/sports"
        params = {"apiKey": self.api_key}

        try:
            response = requests.get(url, params=params, timeout=10)
        except requests.RequestException as e:
            raise OddsAPIError(f"Network error contacting the-odds-api: {e}")

        if response.status_code != 200:
            raise OddsAPIError(
                f"the-odds-api returned {response.status_code} when listing sports: {response.text[:200]}"
            )

        data = response.json()
        leagues = [
            item["key"] for item in data
            if item.get("group") == "Soccer" and item.get("active")
        ]

        self._league_cache = leagues
        self._league_cache_time = time.time()
        return leagues

    def _fetch_league(self, league_key: str) -> List[Dict]:
        url = f"{self.base_url}/sports/{league_key}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": ODDS_API_REGIONS,
            "markets": ODDS_API_MARKETS,
            "oddsFormat": ODDS_API_ODDS_FORMAT,
            "dateFormat": "iso",
        }

        try:
            response = requests.get(url, params=params, timeout=10)
        except requests.RequestException as e:
            raise OddsAPIError(f"Network error fetching {league_key}: {e}")

        if response.status_code != 200:
            raise OddsAPIError(
                f"{league_key} returned {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(hours=MATCH_WINDOW_HOURS)

        matches = []
        for event in data:
            commence_time = self._parse_time(event.get("commence_time"))
            if commence_time is None or not (now <= commence_time <= window_end):
                continue

            home = event.get("home_team", "")
            away = event.get("away_team", "")
            if not home or not away:
                continue

            bookmakers = event.get("bookmakers", [])
            best = self._best_h2h_odds(bookmakers, home, away)
            totals = self._best_totals_odds(bookmakers)

            if best["home"] > 0 and best["draw"] > 0 and best["away"] > 0:
                matches.append({
                    "id": event.get("id", ""),
                    "home_team": home,
                    "away_team": away,
                    "league": league_key.replace("_", " ").title(),
                    "league_key": league_key,
                    "commence_time": commence_time.isoformat(),
                    "odds": best,
                    "totals": totals,   # {"over_2_5": float|None, "under_2_5": float|None}
                })

        return matches

    @staticmethod
    def _best_h2h_odds(bookmakers: List[Dict], home: str, away: str) -> Dict:
        best = {"home": 0, "draw": 0, "away": 0}
        home_l, away_l = home.lower(), away.lower()

        for bookmaker in bookmakers:
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "").lower()
                    price = outcome.get("price", 0)

                    if name == home_l:
                        best["home"] = max(best["home"], price)
                    elif name == away_l:
                        best["away"] = max(best["away"], price)
                    elif name == "draw":
                        best["draw"] = max(best["draw"], price)

        return best

    @staticmethod
    def _best_totals_odds(bookmakers: List[Dict]) -> Dict:
        """Best available Over/Under 2.5 goals odds across bookmakers, if any
        bookmaker offers the totals market at the 2.5 line."""
        best = {"over_2_5": None, "under_2_5": None}

        for bookmaker in bookmakers:
            for market in bookmaker.get("markets", []):
                if market.get("key") != "totals":
                    continue
                for outcome in market.get("outcomes", []):
                    if outcome.get("point") != 2.5:
                        continue
                    name = outcome.get("name", "").lower()
                    price = outcome.get("price", 0)
                    if not price:
                        continue

                    if name == "over":
                        best["over_2_5"] = max(best["over_2_5"] or 0, price)
                    elif name == "under":
                        best["under_2_5"] = max(best["under_2_5"] or 0, price)

        return best

    @staticmethod
    def _parse_time(value: str):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
