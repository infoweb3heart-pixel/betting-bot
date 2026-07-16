from typing import List, Dict
from config import CONFIDENCE_THRESHOLD

class MatchAnalyzer:
    def analyze_matches(self, matches: List[Dict]) -> List[Dict]:
        analyzed = []
        for match in matches:
            analysis = self._analyze_one(match)
            if analysis:
                analyzed.append(analysis)
        return analyzed

    def _analyze_one(self, match: Dict) -> Dict:
        odds = match.get("odds", {})
        home_odds = odds.get("home", 0)
        draw_odds = odds.get("draw", 0)
        away_odds = odds.get("away", 0)

        if not home_odds or not draw_odds or not away_odds:
            return None

        home_imp = 1 / home_odds
        draw_imp = 1 / draw_odds
        away_imp = 1 / away_odds
        total = home_imp + draw_imp + away_imp

        true_home = home_imp / total
        true_draw = draw_imp / total
        true_away = away_imp / total
        margin = total - 1

        best_1x2 = "Unclear"
        best_odds = 0

        if true_home >= true_draw + 0.10:
            best_1x2 = "Home"
            best_odds = home_odds
        elif true_away >= true_draw + 0.10:
            best_1x2 = "Away"
            best_odds = away_odds

        best_dc = "Skip"
        if best_1x2 == "Unclear":
            home_draw = true_home + true_draw
            draw_away = true_draw + true_away
            home_away = true_home + true_away
            if home_draw >= home_away and home_draw >= draw_away:
                best_dc = "1X"
            elif home_away >= home_draw and home_away >= draw_away:
                best_dc = "12"
            else:
                best_dc = "X2"

        confidence = 5
        if best_1x2 != "Unclear":
            confidence += 2
        if margin < 0.08:
            confidence += 1
        if 1.40 <= best_odds <= 2.20:
            confidence += 1

        league = match.get("league", "").lower()
        if any(x in league for x in ["epl", "bundesliga", "serie a", "la liga"]):
            confidence += 1
        if "u20" in league or "reserve" in league or "u21" in league:
            confidence += 1
        if "friendly" in league:
            confidence += 1

        confidence = min(10, confidence)

        return {
            "home_team": match.get("home_team", ""),
            "away_team": match.get("away_team", ""),
            "league": match.get("league", ""),
            "odds": odds,
            "true_home": round(true_home * 100, 1),
            "true_draw": round(true_draw * 100, 1),
            "true_away": round(true_away * 100, 1),
            "best_1x2": best_1x2,
            "best_double_chance": best_dc,
            "confidence_score": confidence,
            "odds_used": best_odds,
            "parlay_eligible": confidence >= CONFIDENCE_THRESHOLD and best_1x2 != "Unclear"
        }