from typing import List, Dict
from config import MAX_PARLAY_LEGS, CONFIDENCE_THRESHOLD

class ParlayBuilder:
    def build_parlay(self, analyzed: List[Dict]) -> Dict:
        eligible = [
            m for m in analyzed
            if m.get("parlay_eligible", False)
            and m.get("confidence_score", 0) >= CONFIDENCE_THRESHOLD
            and m.get("odds_used", 0) > 1.10
        ]

        if len(eligible) < MAX_PARLAY_LEGS:
            return {"error": f"Need {MAX_PARLAY_LEGS} matches. Only found {len(eligible)}."}

        eligible.sort(key=lambda x: x.get("confidence_score", 0), reverse=True)
        selected = eligible[:MAX_PARLAY_LEGS]

        legs = []
        combined_odds = 1
        total_confidence = 0

        for match in selected:
            best = match.get("best_1x2")
            odds = match.get("odds_used", 0)
            confidence = match.get("confidence_score", 0)

            legs.append({
                "home": match.get("home_team", ""),
                "away": match.get("away_team", ""),
                "bet": best,
                "odds": odds,
                "confidence": confidence,
                "prob": match.get("true_home", 0) if best == "Home" else match.get("true_away", 0)
            })

            combined_odds *= odds
            total_confidence += confidence

        avg_confidence = total_confidence / len(legs) if legs else 0
        hit_rate = 0.50 + (avg_confidence - 1) * 0.05
        hit_rate = min(0.95, max(0.50, hit_rate))

        return {
            "legs": legs,
            "combined_odds": round(combined_odds, 2),
            "avg_confidence": round(avg_confidence, 1),
            "hit_rate": round(hit_rate * 100, 1),
            "total_matches": len(eligible)
        }

    def format_message(self, parlay: Dict) -> str:
        if parlay.get("error"):
            return f"⚠️ {parlay.get('error')}"

        legs = parlay.get("legs", [])
        combined = parlay.get("combined_odds", 0)
        hit_rate = parlay.get("hit_rate", 0)

        message = "🎯 **LOW RISK PARLAY**\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        for i, leg in enumerate(legs, 1):
            message += f"**Leg {i}:** {leg.get('home')} vs {leg.get('away')}\n"
            message += f"  📊 Bet: **{leg.get('bet')} Win**\n"
            message += f"  📈 Odds: **{leg.get('odds'):.2f}**\n"
            message += f"  🎯 Confidence: {leg.get('confidence')}/10\n"
            message += f"  📊 True Prob: {leg.get('prob'):.1f}%\n\n"

        message += "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += f"📊 **Combined Odds:** {combined:.2f}\n"
        message += f"🎯 **Hit Rate:** {hit_rate:.0f}%\n"
        message += f"💰 **Stake:** 5% of bankroll\n"
        message += f"📈 **Return:** {combined * 5:.1f}%\n\n"
        message += "⚠️ **Risk:** 🟢 LOW\n💡 Bet responsibly."

        return message