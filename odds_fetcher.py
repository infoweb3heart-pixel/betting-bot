import requests
from typing import List, Dict
from config import ODDS_API_KEY

class OddsFetcher:
    def __init__(self):
        self.api_key = ODDS_API_KEY
        self.base_url = "https://api.the-odds-api.com/v4"

    def fetch_todays_matches(self) -> List[Dict]:
        leagues = ["soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a"]
        all_matches = []

        for league in leagues:
            matches = self._fetch_league(league)
            all_matches.extend(matches)

        if not all_matches:
            return self._get_dummy_matches()

        return all_matches

    def _fetch_league(self, league_key: str) -> List[Dict]:
        url = f"{self.base_url}/sports/{league_key}/odds"
        params = {"apiKey": self.api_key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"}

        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                return []

            data = response.json()
            matches = []

            for event in data:
                home = event.get("home_team", "")
                away = event.get("away_team", "")
                if not home or not away:
                    continue

                bookmakers = event.get("bookmakers", [])
                best = {"home": 0, "draw": 0, "away": 0}

                for bookmaker in bookmakers:
                    markets = bookmaker.get("markets", [])
                    for market in markets:
                        if market.get("key") == "h2h":
                            outcomes = market.get("outcomes", [])
                            for outcome in outcomes:
                                name = outcome.get("name", "").lower()
                                price = outcome.get("price", 0)
                                if home.lower() in name or "home" in name:
                                    if price > best["home"]:
                                        best["home"] = price
                                elif name == "draw":
                                    if price > best["draw"]:
                                        best["draw"] = price
                                elif away.lower() in name or "away" in name:
                                    if price > best["away"]:
                                        best["away"] = price

                if best["home"] > 0 and best["draw"] > 0 and best["away"] > 0:
                    matches.append({
                        "id": event.get("id", ""),
                        "home_team": home,
                        "away_team": away,
                        "league": league_key.replace("_", " ").title(),
                        "odds": best
                    })

            return matches

        except Exception as e:
            print(f"Error: {e}")
            return []

    def _get_dummy_matches(self) -> List[Dict]:
        return [
            {"id": "1", "home_team": "Dinamo Tbilisi", "away_team": "Mondorf", "league": "UEFA Conference League", "odds": {"home": 1.45, "draw": 4.78, "away": 4.60}},
            {"id": "2", "home_team": "Derry City", "away_team": "CSKA Sofia", "league": "UEFA Europa League", "odds": {"home": 3.90, "draw": 3.90, "away": 1.84}},
            {"id": "3", "home_team": "HNK Rijeka", "away_team": "NK Dekani", "league": "Club Friendly", "odds": {"home": 1.18, "draw": 6.00, "away": 11.50}},
            {"id": "4", "home_team": "CA Juventus SP U20", "away_team": "Sertaozinho U20", "league": "Brazil U20 Paulista", "odds": {"home": 1.43, "draw": 4.10, "away": 6.40}},
        ]